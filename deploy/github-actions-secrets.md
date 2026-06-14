# GitHub Actions secrets for production deploy

Required repository secret in GitHub:

- `SINLEX_SSH_KEY` = contents of `/home/ubuntu/.ssh/github_actions_sinlex_ed25519` on the production server

Optional repository secrets, already defaulted in the workflow:

- `SINLEX_SSH_HOST` = `sinlex.tech`
- `SINLEX_SSH_USER` = `ubuntu`
- `SINLEX_SSH_PORT` = `22`

The matching public key is installed in `/home/ubuntu/.ssh/authorized_keys` with a forced command:

```text
sudo /opt/sinlex/deploy/deploy_server.sh
```

This key is intentionally restricted: it cannot open a normal shell session and can only request the deploy command.
