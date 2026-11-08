"""Seed demo HR data into the development site.

Uses ERPNext's programmatic setup wizard when no company exists, then creates
a small, idempotent set of HR masters and employees. Safe to re-run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root, bench_subprocess_env
from cohenix_dev.runtime.processes import redis_running
from cohenix_dev.util import run_command

SEED_MARKER = "cohenix_hr_seed"
DEFAULT_COMPANY = "Cohenix Demo"
DEFAULT_ABBR = "CD"

EMPLOYEES = (
    ("HR-EMP-00001", "Alex", "Developer", "Engineering", "Software Engineer"),
    ("HR-EMP-00002", "Sam", "Manager", "Engineering", "Engineering Manager"),
    ("HR-EMP-00003", "Jordan", "People", "Human Resources", "HR Executive"),
    ("HR-EMP-00004", "Taylor", "Finance", "Finance", "Accountant"),
    ("HR-EMP-00005", "Casey", "Ops", "Operations", "Operations Analyst"),
)


def _seed_script(settings: Settings, *, company: str, abbr: str, force: bool) -> str:
    workspace = Path(settings.workspace).as_posix()
    site = settings.site_name
    sites = (bench_root(settings) / "sites").as_posix()
    employees = repr(list(EMPLOYEES))
    return textwrap.dedent(
        f"""\
        import sys
        sys.path.insert(0, {workspace!r})

        import frappe

        frappe.init(site={site!r}, sites_path={sites!r})
        frappe.connect()
        frappe.set_user("Administrator")

        COMPANY = {company!r}
        ABBR = {abbr!r}
        FORCE = {force!r}
        EMPLOYEES = {employees}
        MARKER = {SEED_MARKER!r}

        def ensure_company():
            if frappe.db.exists("Company", COMPANY):
                return COMPANY
            if "erpnext" not in frappe.get_installed_apps():
                raise SystemExit("erpnext is not installed; use an hr/erp profile before seeding")
            from erpnext.setup.setup_wizard.setup_wizard import setup_complete
            from frappe.utils import today, add_days, get_first_day, get_last_day

            start = get_first_day(today())
            end = get_last_day(add_days(start, 370))
            setup_complete(
                {{
                    "language": "English",
                    "country": "South Africa",
                    "timezone": "Africa/Johannesburg",
                    "currency": "ZAR",
                    "company_name": COMPANY,
                    "company_abbr": ABBR,
                    "chart_of_accounts": "Standard",
                    "fy_start_date": str(start),
                    "fy_end_date": str(end),
                }}
            )
            return COMPANY

        def ensure_employment_type(name):
            existing = frappe.db.exists("Employment Type", name) or frappe.db.exists(
                "Employment Type", {{"employee_type_name": name}}
            )
            if existing:
                return existing if isinstance(existing, str) else name
            doc = frappe.get_doc({{"doctype": "Employment Type", "employee_type_name": name}})
            doc.insert(ignore_permissions=True)
            return doc.name

        def ensure_department(name):
            existing = frappe.db.get_value(
                "Department", {{"department_name": name, "company": COMPANY}}, "name"
            )
            if existing:
                return existing
            doc = frappe.get_doc(
                {{"doctype": "Department", "department_name": name, "company": COMPANY}}
            )
            doc.insert(ignore_permissions=True)
            return doc.name

        def ensure_designation(name):
            existing = frappe.db.exists("Designation", name) or frappe.db.get_value(
                "Designation", {{"designation_name": name}}, "name"
            )
            if existing:
                return existing
            doc = frappe.get_doc({{"doctype": "Designation", "designation_name": name}})
            doc.insert(ignore_permissions=True)
            return doc.name

        def ensure_employee(emp_id, first, last, department, designation):
            existing = frappe.db.exists("Employee", emp_id) or frappe.db.get_value(
                "Employee", {{"employee_number": emp_id}}, "name"
            )
            if existing:
                return existing
            gender = "Other" if frappe.db.exists("Gender", "Other") else (
                "Male" if frappe.db.exists("Gender", "Male") else None
            )
            payload = {{
                "doctype": "Employee",
                "employee_number": emp_id,
                "first_name": first,
                "last_name": last,
                "company": COMPANY,
                "status": "Active",
                "date_of_birth": "1990-01-15",
                "date_of_joining": "2024-01-01",
                "department": department,
                "designation": designation,
                "employment_type": "Full-time",
            }}
            if gender:
                payload["gender"] = gender
            doc = frappe.get_doc(payload)
            doc.insert(ignore_permissions=True)
            return doc.name

        already = frappe.db.get_default(MARKER)
        if already and not FORCE:
            print("cohenix seed: already applied (pass --force to re-check)")
        else:
            apps = set(frappe.get_installed_apps())
            if "erpnext" not in apps:
                raise SystemExit("Need erpnext installed (devctl profile use hr && devctl sync)")
            ensure_company()
            ensure_employment_type("Full-time")
            created = []
            for emp_id, first, last, department, designation in EMPLOYEES:
                dept = ensure_department(department)
                desig = ensure_designation(designation)
                created.append(ensure_employee(emp_id, first, last, dept, desig))
            frappe.db.set_default(MARKER, "1")
            frappe.db.commit()
            print("cohenix seed: company", COMPANY)
            print("cohenix seed: employees", ", ".join(created))

        frappe.destroy()
        """
    )


def seed_hr_demo(
    settings: Settings,
    *,
    company: str = DEFAULT_COMPANY,
    abbr: str = DEFAULT_ABBR,
    force: bool = False,
) -> int:
    root = bench_root(settings)
    python = root / "env" / "bin" / "python"
    if not python.is_file():
        raise CohenixError("Bench env missing; run `devctl sync` first.")
    site_dir = root / "sites" / settings.site_name
    if not site_dir.is_dir():
        raise CohenixError(f"Site {settings.site_name} missing; run `devctl sync` first.")

    script = _seed_script(settings, company=company, abbr=abbr, force=force)
    cprint(f"Seeding HR demo data on {settings.site_name} ...", level=2)
    with redis_running(settings):
        run_command(
            [str(python), "-c", script],
            cwd=str(root / "sites"),
            env=bench_subprocess_env(settings),
        )
    cprint(
        f"Demo company `{company}` with sample employees is ready. "
        f"Open http://{settings.site_name}:{settings.http_port}/app/employee",
        level=2,
    )
    return 0
