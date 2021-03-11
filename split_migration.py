#!/usr/bin/env python

import argparse
from datetime import datetime
from shutil import copyfile, move
import signal
import os

from ruamel.yaml import YAML, comments
from subprocess import Popen, PIPE, STDOUT


def raise_sigint(pid):
    """
    Raising the SIGINT signal in the current process and all sub-processes.

    os.kill() only issues a signal in the current process (without subprocesses).
    CTRL+C on the console sends the signal to the process group (which we need).
    """
    if hasattr(signal, 'CTRL_C_EVENT'):
        # windows. Need CTRL_C_EVENT to raise the signal in the whole process group
        os.kill(pid, signal.CTRL_C_EVENT)
    else:
        # unix.
        pgid = os.getpgid(pid)
        if pgid == 1:
            os.kill(pid, signal.SIGINT)
        else:
            os.killpg(os.getpgid(pid), signal.SIGINT)


def clean(path, element, i=0):
    # Stop invariant when all pathes have been consumed
    if not path:
        return element
    # Allow string pathes (with /) or list
    if isinstance(path, str):
        path = path.split("/")
    if isinstance(element, comments.CommentedMap):
        output = {}
        i += 1
        for k, v in element.items():
            if path[0] == k:
                if path[1:]:
                    output[k] = clean(path[1:], v, i)
            else:
                output[k] = clean(path, v, i)
        return output
    elif isinstance(element, comments.CommentedSeq):
        output = []
        for e in element:
            i += 1
            output.append(clean(path, e, i))
        return output
    return element


ODOODB = "odoodb"
ODOODB_PRE = "odoodb_pre"
ODOODB_POST = "odoodb_post"
ODOODB_TEMPLATE = "odoodb_template"
MARABUNTA_COMMAND = 'docker-compose run --rm -e MARABUNTA_MODE=migration -e DB_NAME=%s odoo rundatabasemigration'
DATABASE_CHECK_COMMAND = 'docker-compose run --rm odoo psql -c "\c %s"'
DATABASE_DROP_COMMAND = 'docker-compose run --rm odoo psql dropdb %s'
DATABASE_CREATE_COMMAND = 'docker-compose run --rm odoo psql createdb %s -T %s'


def cmd_exec(command, *args):
    print("Executing: %s" % (command % args))
    return Popen(
        [command % args],
        shell=True,
        stdout=PIPE,
        stderr=STDOUT,
    ).wait()


if __name__ == "__main__":

    print("Starting procedural migration...")
    Popen(["docker-compose down --remove-orphans"], shell=True)
    is_odoo_database_exists = not cmd_exec(DATABASE_CHECK_COMMAND, ODOODB)
    is_template_database_exists = not cmd_exec(DATABASE_CHECK_COMMAND, ODOODB_TEMPLATE)
    is_pre_database_exists = not cmd_exec(DATABASE_CHECK_COMMAND, ODOODB_PRE)
    is_post_database_exists = not cmd_exec(DATABASE_CHECK_COMMAND, ODOODB_POST)

    if not is_template_database_exists:
        raise Exception(
            "The database 'odoodb_template' must exists to allow migration !"
        )

    if is_odoo_database_exists:
        cmd_exec(DATABASE_DROP_COMMAND, ODOODB)

    date_str = datetime.today().strftime("%Y_%m-%d_%H_%M")
    parser = argparse.ArgumentParser(description='Migration splitter')
    parser.add_argument(
        '--pre',
        action='store_true',
        help='Execute pre phase only (Kill before post setup phase)'
    )
    parser.add_argument(
        '--post',
        action='store_true',
        help='Execute post phase only (Remove pre phase)'
    )

    args = parser.parse_args()
    log_filename = "database_migration_{}.log".format(date_str)
    yaml_file = r'odoo/migration.yml'
    backup_file = r'odoo/migration.yml.bak'

    # Restore if exists or backup migration.yml
    if os.path.isfile(backup_file):
        copyfile(backup_file, yaml_file)
    else:
        copyfile(yaml_file, backup_file)

    DATABASE_TO_MIGRATE = ODOODB

    with open(yaml_file) as input_stream:
        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)
        data = yaml.load(input_stream)
        data_cleaned = data
        if args.pre:
            log_filename += ".pre"
            data_cleaned = clean(
                'migration/versions/modes/migration/operations/post', data)
            data_cleaned = clean(
                'migration/versions/operations/post', data_cleaned)
            data_cleaned = clean(
                'migration/versions/samples/operations/post', data_cleaned)
            if is_pre_database_exists:
                cmd_exec(DATABASE_DROP_COMMAND, ODOODB_PRE)
            Popen(
                [DATABASE_CREATE_COMMAND % (ODOODB_PRE, ODOODB_TEMPLATE)],
                shell=True,
                stdout=PIPE
            ).wait()
            DATABASE_TO_MIGRATE = ODOODB_PRE
        elif args.post:
            data_cleaned = clean(
                'migration/versions/modes/migration/operations/pre', data)
            data_cleaned = clean(
                'migration/versions/operations/pre', data_cleaned)
            data_cleaned = clean(
                'migration/versions/samples/operations/post', data_cleaned)
            log_filename += ".post"
            if is_post_database_exists:
                cmd_exec(DATABASE_DROP_COMMAND, ODOODB_POST)
            if is_pre_database_exists:
                cmd_exec(DATABASE_CREATE_COMMAND, ODOODB_POST, ODOODB_PRE)
            else:
                raise Exception("Pre option hasn't been called yet.")
            DATABASE_TO_MIGRATE = ODOODB_POST
        else:
            cmd_exec(DATABASE_CREATE_COMMAND, ODOODB, ODOODB_TEMPLATE)

        with open(yaml_file, 'w') as output_stream:
            yaml.dump(data_cleaned, output_stream)

    log_output = ""
    try:
        # The os.setsid() is passed in the argument preexec_fn so
        # it's run after the fork() and before  exec() to run the shell.
        popen = Popen(
            [MARABUNTA_COMMAND % (DATABASE_TO_MIGRATE)],
            shell=True,
            stdout=PIPE,
            stderr=STDOUT,
            close_fds=True,
            preexec_fn=os.setsid,
        )
        for binary in popen.stdout:
            line = binary.decode('utf8')
            log_output += line
            if "|> version setup: " in line:
                if args.pre and 'installation / upgrade of addons' in line:
                    # Send the signal to all the process groups
                    os.killpg(os.getpgid(popen.pid), signal.SIGKILL)

                print(line.rstrip("\n"))

    finally:
        # move(backup_file, yaml_file)
        with open(log_filename, 'w') as log_file:
            log_file.write(log_output)
