#!/bin/bash
set -e
if [ ! -e manage.py ]; then echo "Must be run from repo root directory."; exit; fi
dropdb -U juliabase juliabase || true
createdb -U juliabase juliabase
./manage.py migrate
./manage.py loaddata demo_accounts
cd remote_client/examples
./run-crawlers.sh synchronous
python add_informal_stack.py
cd ../..
./manage.py dumpdata --format=yaml --indent=2 --natural-foreign --natural-primary --exclude=sessions.Session \
            > institute/fixtures/test_main.yaml
