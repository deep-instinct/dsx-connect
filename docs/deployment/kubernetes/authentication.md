# Authentication (Kubernetes)

DSX-Connect supports **enrollment-token authentication** between the DSX-Connect API and Connectors. When enabled, Connectors must present a valid enrollment token during registration to establish trust with the API.

For conceptual background, see:
[Concepts → Authentication](../../concepts/authentication.md)

## When to Enable Authentication

Enable enrollment authentication when:

* The DSX-Connect API is reachable outside the namespace (Ingress, shared cluster, multi-team environment)
* You are deploying multiple connectors and want controlled onboarding
* You want a simple bootstrap trust mechanism before issuing longer-lived credentials

Authentication can be left disabled for:

* Local testing
* Fully isolated development clusters

## Requirements

To enable authentication:

1. Set `dsx-connect-api.auth.enabled=true`
2. Create a Kubernetes Secret containing the enrollment token

The Secret name is derived from the Helm release name.

## Step 1: Create the Enrollment Token Secret

The Helm chart includes an example at:

`examples/secrets/auth-enrollment-secret.yaml`

Template:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <release>-dsx-connect-api-auth-enrollment
  namespace: <namespace>
type: Opaque
stringData:
  ENROLLMENT_TOKEN: "change-me-strong-enrollment-token"
```

### Secret Naming Convention

By default, the chart expects:

`<release>-dsx-connect-api-auth-enrollment`

This prevents naming collisions across releases and namespaces.

### Choosing a Strong Token

`ENROLLMENT_TOKEN` should be long and random.

Recommended:

* UUID (minimum)
* 32+ random characters

Example for release `dsx` in namespace `dsx-connect`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dsx-dsx-connect-api-auth-enrollment
  namespace: dsx-connect
type: Opaque
stringData:
  ENROLLMENT_TOKEN: "F0DCA5BB-52CB-4944-BB06-64756B27F8A8"
```

Apply:

```bash
kubectl apply -f examples/secrets/auth-enrollment-secret.yaml
```

### Validate the Secret

```bash
kubectl get secret -n dsx-connect dsx-dsx-connect-api-auth-enrollment
```

Optional key verification:

```bash
kubectl get secret -n dsx-connect dsx-dsx-connect-api-auth-enrollment \
  -o jsonpath='{.data.ENROLLMENT_TOKEN}' | wc -c
```

## Step 2: Enable Authentication in Helm

### Command-Line Override (Quick Test)

```bash
helm upgrade --install dsx -n dsx-connect \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --set dsx-connect-api.auth.enabled=true
```

### Values File (Recommended)

```yaml
dsx-connect-api:
  auth:
    enabled: true
```

Deploy:

```bash
helm upgrade --install dsx . -n dsx-connect -f my-values.yaml
```

---

## Advanced Configuration

Most deployments should not require overrides.

### Override Secret Key Name

If your Secret uses a different key name:

```yaml
dsx-connect-api:
  auth:
    enrollment:
      key: MY_TOKEN_KEY
```

Default is `ENROLLMENT_TOKEN`.

### Override Secret Name

If your chart supports it:

```yaml
dsx-connect-api:
  auth:
    enrollment:
      secretName: my-auth-enrollment-secret
```

If your chart does **not** support overriding the name:

> The enrollment Secret name is derived from the Helm release and is not configurable.

---

## Connector-Side Configuration

When authentication is enabled, Connectors must use the same enrollment token during registration.

Recommended Kubernetes pattern:

```yaml
env:
  DSXCONNECTOR_ENROLLMENT_TOKEN:
    valueFrom:
      secretKeyRef:
        name: dsx-dsx-connect-api-auth-enrollment
        key: ENROLLMENT_TOKEN
```

After successful enrollment, the connector should use the credential issued by DSX-Connect (if applicable).

---

## Rotation Strategy

### Basic Rotation (Downtime Possible)

1. Update the Secret value
2. Restart DSX-Connect API
3. Restart or re-enroll Connectors

### Graceful Rotation (If Supported)

If DSX-Connect supports multiple valid enrollment tokens, configure overlapping tokens temporarily.

If not currently supported:

> Consider implementing dual-token support to allow safe rotation without downtime.


## Troubleshooting

### Connectors receive 401 or 403

Verify:

* `dsx-connect-api.auth.enabled=true`
* Secret exists in the correct namespace
* Secret name matches `<release>-dsx-connect-api-auth-enrollment`
* Secret key matches configured key
* Connector is using the correct token

### API pod crashloops after enabling auth

Common causes:

* Secret missing
* Wrong Secret name
* Missing key
* Secret applied after Helm deployment

Check:

```bash
kubectl describe pod -n dsx-connect <dsx-connect-api-pod>
kubectl logs -n dsx-connect deploy/dsx-dsx-connect-api
kubectl get secret -n dsx-connect | grep auth-enrollment
```

## Security Considerations

* Treat the enrollment token as a password
* Never commit raw tokens to Git
* Use GitOps-friendly secret tooling:

    * SealedSecrets
    * External Secrets Operator
    * SOPS

Do not confuse encryption with authentication:

* TLS without verification is encrypted but unauthenticated
* Production environments should use verified TLS and trusted CA bundles

## Related Pages

* [Concepts → Authentication](../../concepts/authentication.md)
* [Kubernetes → TLS](tls.md)
* [Kubernetes → Deploying DSX-Connect (Helm)](dsx-connect.md)


