# Application Identity and Attribution

An **Application** is a virtual entity registered in DSX-Connect. It represents a real application, service, or other caller and brings together identity bindings, access grants, and attribution defaults. Registering an Application establishes how that caller can use DSX-Connect and how its file activity is attributed.

**File Gateway** names the overall capability: applications discover permitted destinations, submit files, and receive outcomes while DSX-Connect coordinates scanning, policy, repository access, and delivery. Authentication and authorization are steps within that workflow.

![Application identity, access grants, and attribution through file processing](../../assets/diagrams/dsx-connect-2-application-identity.svg#only-light)
![Application identity, access grants, and attribution through file processing](../../assets/diagrams/dsx-connect-2-application-identity-dark.svg#only-dark)

## Operational Boundaries

Application developers receive gateway credentials bound to an Application. They discover allowed destinations and submit files through DSX-Connect. Repository credentials remain with the connectors, operated by internal IT / DevOps.

Enterprise Security defines file-handling policy: scanning, permitted movement, and available dispositions such as quarantine or deletion. Developers handle submission and status in their business applications; the enterprise owns accepted files' processing and disposition. Gateway acceptance and successful repository delivery are separate outcomes.

These boundaries also apply to third-party callers. Their grants determine which operations they may request, while enterprise policy controls file handling. See [Governed File Movement](../../core-concepts/governed-file-movement.md#separation-of-duties-and-operational-boundaries).

## Registering an Application

Operators manage Application records in the **Applications** surface of the Operator Console.

Register the real application by creating its DSX-Connect Application record, adding an identity binding, and assigning grants and attribution defaults. This follows the familiar application-registration pattern used in cloud and identity integrations: a platform-side record represents the software that will call the service. The DSX-Connect registration supplies the file-access and attribution settings used by its workflows.

| Configuration | Purpose |
| --- | --- |
| Application ID and display name | Identify the real caller in jobs and results |
| Enabled status | Control whether the Application may be used |
| Identity bindings | Map a caller credential to the Application |
| Grants | Specify allowed destinations, actions, and path prefixes |
| Attribution defaults | Associate activity with a tenant, customer, business unit, cost center, or billing code |
| Default DSXA protected entity | Supply a scanner reporting identity |
| Operator metadata | Record additional administrative context |

One Application can have access to several destinations, and a destination can serve several Applications. Connector repository permissions must also allow the requested operation.

The current implementation supports static bearer-token bindings. Enterprise identity-provider integration using Entra, Okta, or other OAuth2/OIDC providers is planned.

## From Credential to File Job

1. The real caller presents a credential to the File Gateway.
2. DSX-Connect resolves it to an enabled Application record.
3. The gateway checks destination, action, and path grants for the request.
4. The gateway attaches attribution to the accepted job and its file items.
5. Workers scan and process the files, preserving that context in results.

The caller can use `GET /api/v1/files/destinations` to discover permitted destinations and `POST /api/v1/files/transfers` to upload files. An upload without a destination creates scan-only work.

## Attribution and Reporting

Attribution connects a file's processing history to its organizational owner and submitting Application. It helps operators investigate failures, understand usage, and correlate scanner results with enterprise activity.

| Context | What it identifies |
| --- | --- |
| Application ID and name | The Application associated with the request |
| Tenant and customer | Organizational ownership |
| Business unit | The responsible business function |
| Cost center | Internal accounting ownership |
| Billing code | A project, contract, or other allocation category |
| Submitting principal and authentication method | Who initiated the work and how they authenticated |
| Destination, integration, and scope | Where the requested file operation applies |
| Transfer, job, and item IDs | Correlation across submission and processing |
| File name, size, and hash | The content being evaluated |

Cost-center and billing fields provide allocation context. Their presence does not imply an implemented billing engine, chargeback report, or quota-enforcement service.

### DSXA Context

DSX-Connect uses two channels to carry context into scanning:

- **Protected entity ID:** a DSXA reporting dimension. An Application can specify a default ID referring to a valid protected entity in the management environment.
- **Custom metadata:** richer context such as Application, organizational ownership, destination, and job identifiers accompanies the scan request.

A protected entity ID is distinct from the scanner ID. Use an ID valid for the DSXA management environment receiving the scan.

The gateway derives attribution from the resolved principal, submitted metadata, and destination context. Principal-owned identity and organizational defaults take precedence over caller-supplied values where defined. For the protected entity, the gateway currently checks the principal default first, then submitted metadata, then destination policy. Inspect the resolved job attribution when diagnosing a mapping; the earlier proposed tenant/connector precedence chain is not an implemented contract.

## Example Application Record

This example uses a static binding for a development environment. Production credentials should be managed through an appropriate secret workflow.

```json
{
  "application_id": "claims-upload-service",
  "display_name": "Claims Upload Service",
  "enabled": true,
  "identity_bindings": [
    {"provider": "static_bearer", "token": "<caller-token>"}
  ],
  "tenant_id": "claims-business-unit",
  "business_unit": "Claims",
  "cost_center": "CC-1042",
  "billing_code": "CLAIMS-UPLOAD-PROD",
  "default_protected_entity_id": 65,
  "grants": [
    {
      "destination_ids": ["gcs-claims-intake"],
      "actions": ["discover", "submit", "status"],
      "path_prefixes": ["inbound"]
    }
  ]
}
```

Replace the destination and protected entity IDs with values configured in your environment.

## Planned Extensions

Enterprise token validation and claim mapping, Application quotas, and richer usage reporting are planned extensions. They build on the same Application record and attribution model; the current static-token implementation and stored billing metadata should not be read as confirmation that those extensions are available.

## Related Concepts

- [Connector and Asset Model](../../core-concepts/connectors-and-assets.md)
- [Governed File Movement](../../core-concepts/governed-file-movement.md)
- [Developer File API and Managed File Transfer](../../case-studies/developer-file-api-vs-mft.md)
