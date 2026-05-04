#!/usr/bin/env python3
"""
Project Aegis — Cryptographic Key Generator

Generates all required secrets and writes them to .env.
Existing values are preserved; only missing keys are filled in.

Usage: python scripts/gen-keys.py [--force]
"""
import argparse
import os
import secrets
import sys

ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')

KEYS_TO_GENERATE = [
    'SECRET_KEY',
    'REDIS_PASSWORD',
    'POSTGRES_PASSWORD',
    'BLOCKCHAIN_NODE_KEY',
    'HERMES_SIGNING_KEY',
    'TOKEN_SIGNING_KEY',
    'KILL_SWITCH_KEY',
    'MUNNIN_LICENSE_KEY',
    'PLINXX_LICENSE_KEY',
]

VALIDATOR_TEMPLATE = "node-{i}-{key}"


def load_env(path: str) -> dict[str, str]:
    env = {}
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip()
    return env


def write_env(path: str, env: dict[str, str]) -> None:
    example = os.path.join(os.path.dirname(path), '.env.example')
    if os.path.exists(example):
        with open(example) as f:
            template = f.read()
    else:
        template = '\n'.join(f'{k}=' for k in env) + '\n'

    lines = template.split('\n')
    result = []
    for line in lines:
        if '=' in line and not line.startswith('#'):
            k = line.split('=', 1)[0].strip()
            if k in env and env[k]:
                result.append(f'{k}={env[k]}')
                continue
        result.append(line)
    with open(path, 'w') as f:
        f.write('\n'.join(result))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='Regenerate all keys')
    args = parser.parse_args()

    env = {} if args.force else load_env(ENV_FILE)
    generated = []

    for key in KEYS_TO_GENERATE:
        if not env.get(key):
            env[key] = secrets.token_hex(32)
            generated.append(key)

    # Blockchain validator keys: comma-separated list of 3 node keys
    if not env.get('BLOCKCHAIN_VALIDATOR_KEYS'):
        nodes = [secrets.token_hex(20) for _ in range(3)]
        env['BLOCKCHAIN_VALIDATOR_KEYS'] = ','.join(nodes)
        generated.append('BLOCKCHAIN_VALIDATOR_KEYS')

    write_env(ENV_FILE, env)

    if generated:
        print(f"[Aegis] Generated {len(generated)} key(s):")
        for k in generated:
            print(f"  + {k}")
        print(f"\n[Aegis] Written to {os.path.abspath(ENV_FILE)}")
        print("[Aegis] KEEP THIS FILE SECURE — never commit .env to version control")
    else:
        print("[Aegis] All keys already present. Use --force to regenerate.")


if __name__ == '__main__':
    main()
