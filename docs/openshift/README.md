# OpenShift manifests

Applied in filename order. Full walkthrough with commands:
[`../PROJECT_HANDBOOK.md` → Chapter 13.4](../PROJECT_HANDBOOK.md).

| File | Objects |
|---|---|
| `00-configmap.yaml` | `ConfigMap/capstone2-config` |
| `10-postgres.yaml` | `Service/postgres` (headless), `StatefulSet/postgres` + 5Gi PVC |
| `20-api.yaml` | `Deployment/api`, `Service/api`, `Route/api` |
| `30-customer-dashboard.yaml` | `Deployment`, `Service`, `Route` — app1.py :8501 |
| `40-associates-dashboard.yaml` | `Deployment`, `Service`, `Route` — app2.py :8502 |

**There is no Secret manifest here, deliberately.** `capstone2-secrets` is
created imperatively so no credential is ever committed. Create it *before*
`oc apply`, or every pod will stay in `CreateContainerConfigError`.

```bash
oc create secret generic capstone2-secrets \
  --from-literal=POSTGRES_USER=capstone \
  --from-literal=POSTGRES_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')" \
  --from-literal=POSTGRES_DB=capstone2 \
  --from-literal=JWT_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=FRONTEND_TOKEN_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=ADMIN_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  --from-literal=MANAGER_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  --from-literal=ASSOCIATE_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  --from-literal=AI_API_TOKEN="your-granite-token"
```

Then build the image, apply, and patch the Routes into the ConfigMap:

```bash
oc new-build --name=capstone2 --binary --strategy=docker
oc start-build capstone2 --from-dir=. --follow
oc apply -f docs/openshift/
```

> ⚠️ `PUBLIC_*_URL` in `00-configmap.yaml` is `https://REPLACE-ME` on purpose —
> OpenShift assigns Route hostnames at creation time. Patch them after apply
> (handbook §13.4 step 5) and restart, or cross-app links point at localhost
> and the API's CORS allow-list rejects both dashboards.
