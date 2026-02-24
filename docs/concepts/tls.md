---
title: Transport Security (TLS)
description: How TLS protects DSX-Connect, connectors, and DSXA communications.
---

# Transport Security (TLS)

TLS (Transport Layer Security) encrypts network traffic between:

- Users and the DSX-Connect API
- Connectors and DSX-Connect
- DSX-Connect and DSXA (when applicable)

TLS ensures:

- Confidentiality (traffic cannot be read in transit)
- Integrity (traffic cannot be modified in transit)
- Server authenticity (clients know they are talking to the correct endpoint)

TLS protects data in transit.  
It does not replace authentication.

---

## Why TLS Matters

Without TLS:

- API tokens can be intercepted
- Scan requests can be observed
- File contents transmitted to DSXA could be exposed
- Connectors could be impersonated via man-in-the-middle attacks

Even if DSX-HMAC authentication is enabled, traffic is still visible unless TLS is used.

For production environments, TLS should always be enabled.

---

## What TLS Protects

TLS protects:

- API calls from UI or external clients
- Connector registration traffic
- Scan requests and result submission
- File transfer from connectors to DSXA (if routed over HTTPS)

It does not:

- Replace DSX-HMAC authentication
- Replace authorization controls
- Protect traffic once inside the container runtime

---

## Where TLS Is Terminated

TLS is typically terminated at one of three layers:

### 1) Ingress / Load Balancer (Recommended)

Most common in Kubernetes deployments.

Client → HTTPS → Ingress → HTTP → DSX-Connect

- TLS certificates managed at the ingress layer
- DSX-Connect runs internally over HTTP
- Simplest operational model

---

### 2) Reverse Proxy (Docker or VM deployments)

Client → HTTPS → NGINX / Traefik → HTTP → DSX-Connect

Common for Compose-based deployments.



---

### 3) Directly in DSX-Connect (Less Common)

DSX-Connect may expose HTTPS directly if configured to do so.

This approach:

- Requires certificate management inside the application
- Is less flexible in clustered environments

Ingress termination is generally preferred.

---

## TLS and Authentication Work Together

TLS and DSX-HMAC serve different purposes:

| Feature | Protects |
|----------|----------|
| TLS | Encrypts traffic in transit |
| DSX-HMAC | Verifies connector identity and message integrity |

In production:

- Enable TLS
- Enable authentication
- Restrict network exposure

Together, they provide transport security + identity assurance.

---

## When to Enable TLS

TLS should be enabled in:

- Production environments
- Shared clusters
- Any deployment accessible beyond localhost
- Any deployment across network boundaries

TLS may be skipped for:

- Local development
- Isolated Docker quickstarts

---

## Summary

TLS encrypts traffic.  
Authentication verifies identity.

Production deployments should enable both.