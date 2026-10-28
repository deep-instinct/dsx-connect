# Bug: REST liveness probe fails under token binding

Oct 20, 2026 · @Logan

## Summary and impact

When the scanner's default protected application has a protected-application token, the REST pod's own liveness probe gets 401 and the kubelet restarts the scanner in a loop. Severity: High.

- **Affected:** DSX/A Scanner 4.3.0.2348 REST in cluster (Helm) deployments; seen on the Oct 14 2026 images (not yet retested on the Oct 18 build).
- **Impact:** the REST `dpa` container is killed every few minutes. REST scanning is unavailable during each restart, and the pod shows a growing restart count (96 over about 4 days in our lab).
- **Trigger:** a normal console setting. Customers adopting protected-application tokens on their default application will hit this.

## Environment and steps to reproduce

| Item | Value |
| --- | --- |
| Scanner | 4.3.0.2348 (images of Oct 14 2026), Helm chart 4.3.0.2348, connected to a DSX console |
| Platform | OpenShift 4.22, single node |
| REST settings | `rest.auth_token_secret` set (REST `AUTH` token on); liveness probe as shipped in the chart |
| Probe | exec `/bin/bash /bin/perimeter/Utils/liveness_probe.sh`, initial delay 120 s, every 30 s, 3 failures to restart |

1. In the DSX console, add a protected-application token to the protected application that is the scanner's default.
2. Wait for the scanner to pull the updated policy (a few minutes).
3. Watch the REST pod: `oc get pod -l app=rest -w` and `oc get events --field-selector reason=Unhealthy`.
4. Run the probe by hand: `oc exec deploy/rest-<id> -c dpa -- bash /bin/perimeter/Utils/liveness_probe.sh`.

## Expected vs actual

**Expected:** the liveness probe passes whenever the REST service is healthy, whatever protected-application settings the policy carries.

**Actual:** the probe's test scan is rejected by token binding, so a healthy pod is restarted repeatedly.

```
$ oc exec deploy/rest-1 -c dpa -- bash /bin/perimeter/Utils/liveness_probe.sh
going to test product rest
bad res in test_rest: <Response [401]>
command terminated with exit code 1
```

Event: `Liveness probe failed: going to test product rest ... bad res in test_rest: <Response [401]>`, then `Container dpa failed liveness probe, will be restarted`. The REST `dpa` container reached 96 restarts over about 4 days.

Removing the token from the default protected application stopped the loop: the same probe then printed `test_rest ok`, with 0 restarts afterwards.

## Root cause, workaround and suggested fix

The probe's test scan carries no protected entity and no protected-application token, so it lands on the default protected application and fails its token check.

- `Utils/check_pod_liveness.py`, `test_rest()`, posts a test file to `localhost:5000/scan/binary/v2` with `Content-Type`, `Test-File: dpa-test` and, when `AUTH_TOKEN` is set, `AUTH`.
- It sends no `protected_entity` and no `Protected-Application-Token` header, so `rest_server/di_rest_server.py` checks it against the default entity. That entity has tokens configured, and the check (`is_protected_application_token_invalid`) returns 401.
- ICAP did not show the same restart loop in our tests (3 restarts over the same period), so the ICAP probe path appears unaffected.

**Workaround:** keep the scanner's default protected application free of token binding, and give token-bound applications their own entity IDs that clients name explicitly.

**Suggested fix:**

1. Exempt the internal health check from protected-application token binding. It already identifies itself with `Test-File: dpa-test`, and it comes from localhost.
2. Or give the probe a dedicated health endpoint that does not pass through protected-application checks.
3. Add a regression test: liveness with a token-bound default protected application, with and without the REST `AUTH` token.
