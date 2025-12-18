# Ingress Examples

These ingress examples map to different environments. Apply only what you need:

- `ingress-colima.yaml` – for local Colima k3s clusters using Traefik (port-forward Traefik)
- `ingress-colima-lb.yaml` – Colima with Traefik as a LoadBalancer (no port-forwarding)
- `ingress-kind.yaml` – for local Kind clusters using nginx
- `ingress-aws-alb.yaml` – for AWS EKS with AWS ALB Ingress Controller (untested)
- `ingress-aks-appgw.yaml` – for Azure AKS using Application Gateway Ingress (untested)
- `ingress-openshift-route.yaml` – for OpenShift Routes (untested)

## Exposing Services via Ingress

Apply after deploying dsx-connect provide ingress controllers relevant to the 
kubernetes environment where deployed, to expose the dsx-connect-api.  

### Alternative Approach - Port Mapping
For development and testing, sometimes it's just easier to use port mapping.  Kubectl has a handy
port-forward command built-in:

```bash
kubectl port-forward svc/dsx-connect-api 8586:8586
```
and then dsx-connect-api can be accessed with: http://localhost:8586
This can easily be used for demos and testing, and potentially POVs, however, just know that the
port-forward runs in the foreground and holds the connection open. When you kill it
(e.g., with Ctrl+C), the port-forwarding tunnel shuts down.  You can run in the background, but
overall that's a bit hokey for something like POV (in my opinion, it "hides" how you are exposing the
internal service, which can lead to confusion).

The more proper, kubernetes way to expose a service is via ingress controllers.  The following is an example of 
deploying ingress in the local kubernetes dev platform KIND.

### Colima (k3s + Traefik)
Colima can run a single‑node k3s cluster locally (`colima start --kubernetes`). k3s typically ships with Traefik as the default ingress controller.

1) Verify Traefik is present and discover the service name/namespace:
```bash
kubectl -n kube-system get svc traefik
```

2) Apply the Colima ingress example to route host traffic to `dsx-connect-api`:
```bash
kubectl apply -f dsx_connect/deploy/helm/examples/ingress/ingress-colima.yaml
```

3) Port‑forward to Traefik to expose it on localhost (since there’s no external LB):
```bash
kubectl -n kube-system port-forward svc/traefik 8080:80
```

4) Access the API through Traefik using nip.io:
```
http://dsx-connect.127.0.0.1.nip.io:8080
```

#### Colima with Traefik as LoadBalancer (no port-forwarding)
On Colima’s k3s, you can expose Traefik with a LoadBalancer using the built-in ServiceLB (klipper). This provides an External IP you can hit directly from your host.

1) (Recommended) Start Colima with a routable VM IP:
```bash
colima stop
colima start --kubernetes --network-address
```

2) Run the helper script to switch Traefik to LoadBalancer, wait for an External IP, and apply the ingress:
```bash
scripts/setup-colima-traefik-lb.sh
```

3) Access without port-forwarding:
```
http://dsx-connect.<EXTERNAL-IP>.nip.io
```

Optional TLS at Traefik:
```bash
kubectl create secret tls dsx-connect-colima-tls \
  --cert=shared/deploy/certs/dev.localhost.crt \
  --key=shared/deploy/certs/dev.localhost.key -n default

# Then uncomment the tls: block in ingress-colima-lb.yaml (or patch it),
# and access via https (Traefik’s 443 will be on the same External IP):
https://dsx-connect.<EXTERNAL-IP>.nip.io
```

### Deploy an Ingress Controller for KIND
NOTE: this example just demonstrates how to install and ingress controller in KIND, using nginx ingress controller and
ni.io for the purpose of developing and testing ingress.  You will still need to port forward to the ingress controller,
so, if you are just wanting to use dsx-connect, the following doesn't really gain you anything. 

#### Deploy an Ingress Controller 
1. Make sure that the KIND node is ingress enabled.  Find the name of the node:
```shell
kubectl get nodes
```
and you'll get something like this:
```
NAME                            STATUS   ROLES           AGE   VERSION
dsx-connect-dev-control-plane   Ready    control-plane   15h   v1.33.1
```
2. Then, add a label to the node: 
```shell
kubectl label node <node name> ingress-ready=true
```

3. Install NGINX Ingress:
```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/kind/deploy.yaml
```

Wait until ready:
```bash
kubectl get pods -n ingress-nginx
```

4. Apply ingress-kind:
```shell
kubectl apply -f dsx_connect/deploy/helm/examples/ingress/ingress-kind.yaml
```

5. Check status:
```shell
kubectl get ingress
```
Result should show the port and "hostname":
```less
NAME              CLASS    HOSTS                          ADDRESS     PORTS   AGE
dsx-connect-api   <none>   dsx-connect.127.0.0.1.nip.io   localhost   80      23s
```

#### Port Forward to the Ingress Controller

```less
kubectl port-forward svc/ingress-nginx-controller -n ingress-nginx 8080:80
```
Use a browser to use dsx-connect:
http://dsx-connect.127.0.0.1.nip.io:8080
