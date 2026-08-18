<div align="center">
    <h2>Cohenix - Frappe Local Development Container</h2>

</div>

This repository is maintained by Cohenix, a subsidiary of the Group Elephant Fund and part of the EPI-USE group of companies. Our solution builds on the Frappe.io framework, integrating custom modules tailored to client needs. For inquiries, terms of use or contributions, please contact the Cohenix development team at christiaan.swart@epiuse.com

## Introduction

Chohenix devcontainer allow quick and easy setup of the development environment on local VS Code instance, a ready out of the box development environment.

## Frappe Repositories

- cohenix_erp
- cohenix_hr
- cohenix_crm
- cohenix_learning
- cohenix_payment
- cohenix_helpdesk

## Index / Quick links
* [Prerequisites](#prerequisites)
* [How to Setup](#how-to-setup)
* [After the Install](#after-the-install)
* [Running Bench Commands](#running-bench-commands)
* [Git Commands](#git-commands)

## Prerequisites

    Please note:

    The following software and accounts are required to run a succefull docker development environment, if you have not installed or created accounts for the following please do so now before moving on.
    
    If you rquire instructions in how to install the following please refer to the Cohenix development resource: https://github.com/epiusegs/cohenix_dev_resources

- VS Code

      https://code.visualstudio.com/

- Git

      https://git-scm.com/

- GitHub

      https://github.com/

- Docker

      https://docs.docker.com/get-started/get-docker/

- Docker Desktop

      https://docs.docker.com/desktop/

## How to Setup

* [Initial Container Setup](#initial-container-setup)
* [Switch Between Containers](#switch-between-containers)

### Initial Container Setup
- Create a folder where you will clone the git repository projects (example: projects)
- Navigate to the folder
  - cd < your folder >

- Clone repository
  - git clone https://github.com/EPIUSECX/frappe_cohenix_development.git
  
    ![COHENIX_DEVCONTAINERS](images/devcontainer_01.png)

- Open VS Code and installed the following plugins.
  - Container Tools
  - Database Client
  - Database Client JDBC
  - Docker

    ![COHENIX_DEVCONTAINERS](images/devcontainer_02.png)
 
- While In VS Code select "Open folder"
- Navigate to the project folder that was created in first step
- Select the project that you have cloned
  - (example: frappe_cohenix_development)

    ![COHENIX_DEVCONTAINERS](images/devcontainer_03.png)
  
- VS Code will open the project and prompt you to "Reopen in Dev Container" click button to confirm:

    ![COHENIX_DEVCONTAINERS](images/devcontainer_04.png)
  
- The initial docker image will be pulled and installed, you can view the image in Docker Desktop:
  
    ![COHENIX_DEVCONTAINERS](images/devcontainer_05.png)
  
- In VS Code the script will then be run and you will be able to view the progress in the 
  "development-bench" Logs folder:
  
    ![COHENIX_DEVCONTAINERS](images/devcontainer_06.png)

- Once the script has finished runnig you can now safely cd to the bench folder and run commands (cd development-bench/)

    ![COHENIX_DEVCONTAINERS](images/devcontainer_07.png)

    ![COHENIX_DEVCONTAINERS](images/devcontainer_08.png)

## After the Install

The bench is managed by [Pilot](https://github.com/frappe/pilot), which replaces
frappe/bench 5.x as the bench manager. Pilot's own executable is also called
`bench`, so `installer.py` installs it under the name **`pilot`** instead — the
classic `bench` command is untouched and still works (see
[Running Bench Commands](#running-bench-commands)).

Benches live at `pilot/benches/<name>`. The installer drops a symlink at
`development-bench` so the familiar path keeps working.

The container and Pilot release are pinned so rebuilding the same commit does
not silently pick up a different toolchain. To override a version locally, copy
`.devcontainer/.env.example` to `.devcontainer/.env`, edit it, and rebuild the
container. `PILOT_VERSION=latest` is supported for experiments, but is deliberately
not the default.

After provisioning, the installer verifies the runtime, app checkouts, built
assets, and sites. It records the resolved app commits (without passwords) in
`development-bench/.provisioning.json`. Re-run the checks without changing the
environment at any time:

    python installer.py --verify-only

### 1. Site address

The default site is `http://cohenix.localhost:8000/app`. The `.localhost` suffix
resolves to loopback automatically on macOS, Linux, and Windows, so it needs no
hosts-file entry.

If you choose a custom name such as `development.cohenix`, add it on your **host
machine** (not inside the container):

    echo "127.0.0.1 development.cohenix" | sudo tee -a /etc/hosts

Without this a custom name gets `DNS_PROBE_FINISHED_NXDOMAIN`. `http://localhost:8000` works
either way. Remember the `:8000` — a bare hostname goes to port 80 and gives
`ERR_CONNECTION_REFUSED`.

The installer prints this line at the end of its run when the site name is not a
`.localhost` name.

### 2. Start the bench

The devcontainer `postStartCommand` starts it automatically each time the
container starts and avoids launching a duplicate process. Startup output is in
`/tmp/pilot-development-bench.log`. To start or restart it by hand:

    pilot -b development-bench start

This is the foreground runner — the direct equivalent of the old `bench start`.
It starts web, workers, socket.io, Pilot's own Redis, and the admin UI. Stop with
Ctrl-C, or:

    pilot -b development-bench stop

| What | Where |
|---|---|
| Site | http://cohenix.localhost:8000/app |
| Pilot admin UI | http://localhost:8002 |
| Mailpit | http://localhost:8025 |

The admin UI password is in `pilot/benches/development-bench/bench.toml` under
`[admin]`. The site Administrator password is whatever `--admin-password` was set
to (default `admin`).

### Useful Pilot commands

| Command | Purpose |
|---|---|
| `pilot ls` | List benches, status and admin URL |
| `pilot -b development-bench start` | Start all processes |
| `pilot -b development-bench stop` | Stop all processes |
| `pilot -b development-bench get-app <repo>` | Clone and install an app |
| `pilot -b development-bench install-app <app> --site <site>` | Install an app on a site |
| `pilot -b development-bench new-site <site>` | Create a site |
| `pilot -b development-bench frappe --site <site> <cmd>` | Run any frappe CLI command |

## Running Bench Commands

Classic `bench` commands still work. Change into the bench directory first:

    cd development-bench
    bench --site cohenix.localhost migrate
    bench --site cohenix.localhost console
    bench build

`migrate`, `build`, `console`, `execute`, `install-app`, `backup` and
`set-config` all behave normally.

**Do not run `bench start` here.** Pilot writes no `Procfile` and runs its own
process set — use `pilot -b development-bench start` instead.

If a bench command reports `WARN: Command not being executed in bench directory`,
the `config/pids` directory is missing. frappe/bench requires it; Pilot keeps its
pid files elsewhere. The installer creates it, and it is safe to recreate:

    mkdir -p development-bench/config/pids

Pilot's passthrough runs the same frappe commands from any directory, without the
`cd`:

    pilot -b development-bench frappe --site cohenix.localhost migrate

### Switch Between Containers
- To switch between containers navigate to the bottom left corner and select the container icon

    ![COHENIX_DEVCONTAINERS](images/devcontainer_09.png)

- Close the current remote connection if you are still in a docker container.

    ![COHENIX_DEVCONTAINERS](images/devcontainer_10.png)

- Navigate to the Explorer sidebar, you will need to delete the folder "cohenix-bench" folder before recreating the container to avoid any conflicts.

    ![COHENIX_DEVCONTAINERS](images/devcontainer_11.png)

- Navigate to your VS Code Terminal, make sure you are in the "cohenix-devcontainers" folder.

    ![COHENIX_DEVCONTAINERS](images/devcontainer_12.png)

- Check your current branch and then switch to your intended branch or create a new branch
  - check your current branch

        git branch

      ![COHENIX_DEVCONTAINERS](images/devcontainer_13.png)

  - switch to your intended branch

      ![COHENIX_DEVCONTAINERS](images/devcontainer_14.png)

  - or Create a new branch

      ![COHENIX_DEVCONTAINERS](images/devcontainer_15.png)

- Navigate to the bottom left corner and select the container icon

    ![COHENIX_DEVCONTAINERS](images/devcontainer_09.png)

- Select reopen container

    ![COHENIX_DEVCONTAINERS](images/devcontainer_16.png)

- The container wil re-open. Your VS Code frame change to blue indicating the you are in the containers.

    ![COHENIX_DEVCONTAINERS](images/devcontainer_17.png)

- The Container is still referencing the previous build so you will need to re-build the container.
- Navigate to the bottom left corner and select the container icon

    ![COHENIX_DEVCONTAINERS](images/devcontainer_09.png)

- Select rebuild Container container

    ![COHENIX_DEVCONTAINERS](images/devcontainer_18.png)

- Wait until the container is build, your container environment should be ready.

## Git Commands

### Setting up a Repository:
- Initializes a new Git repository in the current directory.

        git init

- Creates a local copy of a remote repository.

        git clone <repository_url>

- Sets your global username for Git commits.

        git config --global user.name "Your Name"

- Sets your global email for Git commits.

        git config --global user.email "your_email@example.com"

### Making and Saving Changes:
- Shows the status of your working directory and staged files. 

        git status

- Adds a specific file to the staging area. 

        git add <file_path>

- Adds all changes in the current directory to the staging area.

        git add .

- Records the staged changes to the repository with a descriptive message.

        git commit -m "Commit message"

### Branching and Merging:
- Lists all local branches.

        git branch

- Temporarily saves modified tracked files, allowing you to switch contexts and then reapply them later. 

        git stash

- Creates a new branch.

        git branch <branch_name>

- Switches to a different branch.

        git checkout <branch_name>

- Creates a new branch and switches to it. 

        git checkout -b <new_branch_name>

- Merges the specified branch into the current branch.

        git merge <branch_name>



### Working with Remote Repositories:
- Uploads local commits to the remote repository.

        git push

- Fetches and merges changes from the remote repository.

        git pull
