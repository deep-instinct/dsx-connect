# Docker Installation

DSX-Connect runs in containers.  
To run it locally or deploy it to Kubernetes, you need a working Docker environment.

This page explains your platform options — and our recommendations.

---

## 🧭 Production vs Development

!!! warning "Production Guidance"
    Docker Desktop is **not recommended** for production workloads.  
    Production DSX-Connect deployments should run on **Linux hosts** or **Kubernetes nodes** using native container runtimes.

!!! note "Development Guidance"
    macOS and Windows require a lightweight Linux VM to run containers.  
    Docker Desktop is the fastest way to get started, but alternatives exist.

---

## 🐧 Linux (Recommended for Production)

On Linux, Docker runs **natively**.  
There is no hidden virtual machine and no additional overhead.

### ✅ Recommended: Docker Engine

Official installation guide:

https://docs.docker.com/engine/install/

Supported distributions include:

- Ubuntu
- Debian
- RHEL / Rocky / Alma
- Fedora
- SLES

!!! tip "Best Choice for DSX-Connect"
    Native Linux Docker is:
    
    - Ideal for production
    - Ideal for Kubernetes worker nodes
    - Ideal for CI/CD runners
    - Lower overhead than Desktop variants

After installation validation:

```bash
docker version
docker run hello-world
```

---

## 🍎 macOS (Development Only)

Docker does **not** run natively on macOS.
It always runs inside a lightweight Linux VM.

You have two solid options.

---

### Recommended: Option 1 — Colima (Lean, Developer-Friendly, K8S support)

Project page:

[https://github.com/abiosoft/colima](https://github.com/abiosoft/colima)

Colima uses Lima + containerd to provide a lightweight Docker-compatible runtime.

!!! tip "Best Choice for DSX-Connect on Mac"
    Colima is:

    - Ideal for development
    - Lightweight and easy to install
    - Easy to switch between Linux distributions
    - Lightweight Kubernetes (k3s) built-in - so you can test Kubernetes deployments locally

#### Pros

* Lower resource usage
* Fully open-source
* No Docker Desktop licensing concerns
* Excellent CLI experience

#### Cons

* No GUI dashboard
* Slightly more manual setup

!!! tip
    If you prefer lightweight tooling and minimal overhead, Colima is an excellent choice for DSX-Connect development.


### Option 2 — Docker Desktop (Fastest Setup)

Official install guide:

[https://docs.docker.com/desktop/install/mac-install/](https://docs.docker.com/desktop/install/mac-install/)

#### Pros

* Simple installation
* GUI dashboard
* Optional built-in Kubernetes
* Automatic VM lifecycle management

#### Cons

* Higher memory usage
* Licensing considerations in some organizations
* Hidden VM layer

!!! note
    For most developers evaluating DSX-Connect, this is the quickest path.

---

## 🪟 Windows (Development Only)

Docker does **not** run natively on Windows.
It requires WSL2 (Windows Subsystem for Linux).

---

### ✅ Recommended: Docker Desktop (WSL2 Backend)

Official guide:

[https://docs.docker.com/desktop/install/windows-install/](https://docs.docker.com/desktop/install/windows-install/)

#### Requirements

* Windows 10/11 Pro, Enterprise, or Education
* WSL2 enabled

Docker Desktop integrates with:

* Windows Terminal
* PowerShell
* VS Code

!!! note
    Docker Desktop on Windows runs containers inside WSL2.
    You are effectively running Linux containers inside a managed Linux environment.

---

### Advanced Option — Manual WSL2 + Docker Engine

Advanced users may:

1. Install WSL2
2. Install Ubuntu (or similar)
3. Install Docker Engine directly inside WSL

This avoids Docker Desktop but requires more configuration.

---

## 🚫 Why We Do Not Recommend Docker Desktop for Production

Docker Desktop is designed for **developer workstations**, not servers.

Reasons:

* Runs inside a VM
* Adds additional resource overhead
* Not designed for high-availability workloads
* Licensing constraints in enterprise environments
* Not appropriate for Kubernetes production nodes

!!! Warning
    Do not deploy DSX-Connect production workloads on Docker Desktop.

For production:

* Use Linux hosts
* Use Kubernetes clusters
* Use native container runtimes (Docker Engine, containerd)

---

## ☸️ Relationship to Kubernetes & Helm

DSX-Connect production deployments use Helm charts and Kubernetes.

In that model:

* Containers run on Linux nodes
* Networking is handled by Kubernetes Services
* Container runtime is native (Docker or containerd)
* No Desktop VM layer exists

Your local Docker setup simply simulates:

```
Developer Machine → Containers → DSX-Connect
```

Production architecture looks like:

```
Kubernetes Cluster
    ├── DSX-Connect API Pods
    ├── Worker Pods
    ├── Redis
    └── (Optional) DSXA Scanner
```

!!! tip
    If your goal is production parity, Linux + Kubernetes is the closest match to real deployments.

---

## 📊 Platform Comparison

| Platform | Native Containers | Recommended              | Intended Use                  |
| -------- | ----------------- | ------------------------ | ----------------------------- |
| Linux    | Yes               | Docker Engine            | Production, CI/CD, Kubernetes |
| macOS    | No                | Docker Desktop or Colima | Development                   |
| Windows  | No                | Docker Desktop (WSL2)    | Development                   |

---

## ✅ Verify Your Installation

After installing Docker:

```bash
docker version
docker run hello-world
```

Both commands must succeed before running DSX-Connect.

If Docker is not fully operational, DSX-Connect containers will fail to start.

