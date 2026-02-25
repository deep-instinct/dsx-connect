# Containers Are Not Virtual Machines

One of the most common misunderstandings when learning Docker or Kubernetes is assuming containers behave like virtual machines, as in, containers run _inside_ Dockers or Kubernetes nodes.

They do not.

---

## 🧠 Key Concept

Containers are **isolated processes running on the host’s Linux kernel**.

They are:

- Namespaced
- Resource limited (cgroups)
- Filesystem isolated
- Network isolated

But they are still **regular Linux processes**.

---

## What This Means in Practice

If you run Docker on a Linux host and start DSX-Connect:

```bash
docker compose up -d
````

You can run:

```bash
top
```

or:

```bash
ps aux
```

And you will see:

* The API process
* Worker processes
* Redis
* Any other containerized services

They are not hidden inside a VM.

They are processes managed by the Linux kernel.

---

## 🆚 Virtual Machines vs Containers

### Virtual Machine

```text
Host OS
  └── Hypervisor
        └── Guest OS
              └── Application
```

A VM:

* Runs a full guest operating system
* Has its own kernel
* Virtualizes hardware

---

### Container

```text
Linux Kernel
  ├── Container Runtime (Docker/containerd - configures isolation)
  ├── DSX-Connect API Process
  ├── Worker Process
  └── Redis Process
```

A container:

* Shares the host kernel
* Does not boot a guest OS
* Starts almost instantly
* Has much lower overhead

---

## Kubernetes Does the Same Thing

When you deploy DSX-Connect to Kubernetes:

* Pods are still just containers
* Containers are still just processes
* The Linux node runs them directly

If you SSH into a Kubernetes node and run:

```bash
top
```

You will see:

* kubelet
* container runtime
* Your DSX-Connect API processes
* Worker processes
* Redis processes

Kubernetes is an orchestrator.
It does not create virtual machines.

---

## Why This Matters

Understanding this helps you reason about:

* CPU and memory usage
* Process crashes
* Resource limits
* Security boundaries
* Observability

Containers are process isolation _on Linux_ — not hardware virtualization.

Next: See [Evolution of Docker](evolutionofdocker.md)

