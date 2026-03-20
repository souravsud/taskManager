# SSH Setup Guide

This guide explains how to configure SSH access for the toolkit.

### Passwordless SSH login

Generate an SSH key pair (if you don't already have one) and copy the public key to the cluster:

```bash
ssh-keygen -t ed25519 -C "your-email@example.com"
ssh-copy-id your-cluster-hostname
```

Verify that you can log in without being prompted for a password:

```bash
ssh your-cluster-hostname "echo ok"
```

If your cluster username differs from your local username, add a `User` directive to `~/.ssh/config` (see the ControlMaster section below) rather than embedding it in every command.

### SSH ControlMaster (connection reuse)

The toolkit opens many short SSH connections in quick succession (status checks, file transfers, job submissions). Adding a `ControlMaster` / `ControlPersist` stanza to your `~/.ssh/config` reuses the same TCP connection for all of them, which avoids repeated authentication handshakes and dramatically speeds things up:

```
Host your-cluster-hostname
    User your-cluster-username
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
```

Replace `your-cluster-hostname` with the value you set in `cluster.host`.

### Known hosts

Make sure the cluster host is already in `~/.ssh/known_hosts` (i.e., you have logged in at least once and accepted the host fingerprint). If not, do so before running the toolkit:

```bash
ssh-keyscan -H your-cluster-hostname >> ~/.ssh/known_hosts
```