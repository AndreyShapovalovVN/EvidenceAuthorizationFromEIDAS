# Встановлення в Kubernetes

Цей документ описує базовий деплой сервісу авторизації в Kubernetes для DevOps-команди.

## 1. Передумови

- Kubernetes-кластер `v1.25+`;
- `kubectl` з доступом до цільового namespace;
- зібраний Docker image сервісу;
- Redis у кластері або зовнішній керований Redis-сервіс.

## 2. Рекомендовані змінні

- `NAMESPACE=authorization`
- `APP_NAME=authorization-ui`
- `IMAGE=ghcr.io/<github-username>/<repo-name>:<tag>`
- `REDIS_URL=redis://redis:6379/0`
- `REDIS_TTL=86400`
- `REDIS_PREFIX=`

## 3. Створення namespace

```bash
kubectl create namespace authorization
```

## 4. Створення Secret і ConfigMap

```bash
kubectl -n authorization create secret generic authorization-secrets \
  --from-literal=REDIS_URL='redis://redis:6379/0'

kubectl -n authorization create configmap authorization-config \
  --from-literal=REDIS_TTL='86400' \
  --from-literal=REDIS_PREFIX=''
```

## 5. Deployment і Service

Створіть файл `authorization-k8s.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: authorization-ui
  namespace: authorization
  labels:
    app: authorization-ui
spec:
  replicas: 2
  selector:
    matchLabels:
      app: authorization-ui
  template:
    metadata:
      labels:
        app: authorization-ui
    spec:
      containers:
        - name: authorization-ui
          image: ghcr.io/<github-username>/<repo-name>:<tag>
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
          env:
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: authorization-secrets
                  key: REDIS_URL
            - name: REDIS_TTL
              valueFrom:
                configMapKeyRef:
                  name: authorization-config
                  key: REDIS_TTL
            - name: REDIS_PREFIX
              valueFrom:
                configMapKeyRef:
                  name: authorization-config
                  key: REDIS_PREFIX
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 20
            timeoutSeconds: 2
            failureThreshold: 3
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: authorization-ui
  namespace: authorization
spec:
  selector:
    app: authorization-ui
  ports:
    - name: http
      port: 80
      targetPort: 8000
  type: ClusterIP
```

Застосуйте маніфест:

```bash
kubectl apply -f authorization-k8s.yaml
```

## 6. Ingress (необов'язково)

Якщо використовується Ingress Controller, наприклад NGINX, можна додати `authorization-ingress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: authorization-ui
  namespace: authorization
spec:
  rules:
    - host: auth.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: authorization-ui
                port:
                  number: 80
```

Застосування:

```bash
kubectl apply -f authorization-ingress.yaml
```

## 7. Перевірка деплою

```bash
kubectl -n authorization get pods
kubectl -n authorization get svc
kubectl -n authorization logs deploy/authorization-ui --tail=100
kubectl -n authorization port-forward svc/authorization-ui 8080:80
```

Перевірка health endpoint:

```bash
curl -sS http://127.0.0.1:8080/health
```

## 8. Що врахувати в production

- сервіс залежить від Redis, тому недоступний Redis призведе до `503` на `/health`;
- для rolling update бажано мати щонайменше `replicas: 2`;
- варто додати HPA, PodDisruptionBudget і NetworkPolicy;
- секрети краще зберігати через Vault, External Secrets або аналогічний механізм, а не через literal-команди;
- якщо використовується зовнішній Redis, обмежте мережевий доступ до нього.

## 9. Рекомендований CI/CD-потік

1. Зібрати Docker image з `Dockerfile`.
2. Опублікувати image в реєстр, наприклад `ghcr.io`.
3. Оновити тег image в Kubernetes-маніфестах.
4. Застосувати зміни через `kubectl apply` або GitOps-інструмент, наприклад Argo CD чи Flux.

