#!/usr/bin/env python

import argparse
import pyodbc
import requests

from asana2sql.fields import default_fields
from asana2sql.Project import Project
from asana2sql.workspace import Workspace
from asana2sql.db_wrapper import DatabaseWrapper
from asana import Client, session

def arg_parser():
    parser = argparse.ArgumentParser()

    # Global options
    parser.add_argument(
            '--project_id',
            type=int,
            required=True,
            help="Asana project ID.")

    parser.add_argument(
            '--table_name',
            help=("Name of the SQL table to use for tasks."
                  "If not specified it will be derived from the project name."))

    parser.add_argument(
            '--dump_perf',
            action="store_true",
            default=False,
            help="Print performance information on completion.")

    parser.add_argument("--projects_table_name")
    parser.add_argument("--project_memberships_table_name")
    parser.add_argument("--users_table_name")
    parser.add_argument("--followers_table_name")
    parser.add_argument("--custom_fields_table_name")
    parser.add_argument("--custom_field_enum_values_table_name")
    parser.add_argument("--custom_field_values_table_name")

    # Asana Client options
    asana_args = parser.add_argument_group('Asana Client Options')

    asana_args.add_argument(
            "--access_token",
            required=True,
            help="Asana Personal Access Token for authentication.")

    asana_args.add_argument(
            "--base_url",
            default="https://app.asana.com/api/1.0",
            help="URL of the Asana API server.")

    asana_args.add_argument(
            "--no_verify",
            dest="verify",
            default=True,
            action="store_false",
            help="Turn off HTTPS verification.")

    asana_args.add_argument(
            "--dump_api",
            action="store_true",
            default=False,
            help="Dump API requests to STDOUT")

    # DB options
    db_args = parser.add_argument_group('Database Options')

    db_args.add_argument(
            "--odbc_string",
            help="ODBC connection string.")

    db_args.add_argument(
            "--dump_sql",
            action="store_true",
            default=False,
            help="Dump SQL commands to STDOUT.")

    db_args.add_argument(
            "--dry",
            action="store_true",
            default=False,
            help="Dry run.  Do not actually run any writes to the database.")

    # Commands
    subparsers = parser.add_subparsers(
            title="Commands",
            dest="command")

    create_table_parser = subparsers.add_parser(
            'create',
            help="Create tables for the project.")

    export_parser = subparsers.add_parser(
            'export',
            help="Export the tasks in the project, "
                 "not deleting deleted tasks from the database.")

    export_parser = subparsers.add_parser(
            'synchronize',
            help="Syncrhonize the tasks in the project with the database.")

    return parser

def build_asana_client(args):
    options = {
        'session': session.AsanaOAuth2Session(
            token={'access_token': args.access_token})}

    if args.base_url:
        options['base_url'] = args.base_url
    if args.verify is not None:
        # urllib3.disable_warnings()
        options['verify'] = args.verify
    if args.dump_api:
        options['dump_api'] = args.dump_api

    return RequestCountingClient(**options);

class RequestCountingClient(Client):
    def __init__(self, dump_api=False, session=None, auth=None, **options):
        Client.__init__(self, session=session, auth=auth, **options)
        self._dump_api = dump_api
        self._num_requests = 0

    @property
    def num_requests(self):
        return self._num_requests

    def request(self, method, path, **options):
        if self._dump_api:
            print("{}: {}".format(method, path))
        self._num_requests += 1
        return Client.request(self, method, path, **options)

def main():
    args = arg_parser().parse_args()
    
    client = build_asana_client(args)

    db_client = None
    if args.odbc_string:
        print("Connecting to database.")
        db_client = pyodbc.connect(args.odbc_string)

    db_wrapper = DatabaseWrapper(db_client, dump_sql=args.dump_sql, dry=args.dry)
    print("workspace...")
    workspace = Workspace(client, db_wrapper, args)
    print("project...")
    project = Project(
            client, db_wrapper, workspace, args, default_fields(workspace))

    if args.command == 'create':
        print("create...")
        project.create_table()
        workspace.create_tables()
    elif args.command == 'export':
        project.export()
    elif args.command == 'synchronize':
        project.synchronize()

    if not args.dry:
        db_client.commit()

    if args.dump_perf:
        print("API Requests: {}".format(client.num_requests))
        print("DB Commands: reads = {}, writes = {}, executed = {}".format(
            db_wrapper.num_reads, db_wrapper.num_writes, db_wrapper.num_commands_executed))

if __name__ == '__main__':
    for driver in pyodbc.drivers():
        print(driver)
    main()

