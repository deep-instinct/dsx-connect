
## Asset vs Filter

* **Asset** defines the coarse scan boundary (host path).
* **Filters** apply include/exclude rules under that boundary.

See:

* [Core Concepts → Connector Model](/concepts/connectors.md)
* Reference → Filters
* Concepts → Performance & Throughput

--- 

## TLS

If DSX-Connect Core is using TLS, update:

```bash
DSXCONNECTOR_DSX_CONNECT_URL=https://dsx-connect-api:8586
```

See:

> Deployment → Docker Compose → TLS