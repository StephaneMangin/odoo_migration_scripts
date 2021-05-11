#!/usr/bin/env python
import json
import logging

import click

from odoo_module_graph import OdooModules

_logger = logging.getLogger(__name__)


def formatted_print(obj):
    print(json.dumps(obj, sort_keys=True, indent=4, ensure_ascii=False))


@click.group()
@click.option('--database', "-d", help='Database name')
@click.pass_context
def cli(ctx, database):
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)
    ctx.obj['database'] = database


@cli.command(name='optimize_dependencies')
@click.option('--restrict-path', help='A specific path to search modules from')
@click.pass_context
def optimize_dependencies(ctx, restrict_path=None):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    modules = odoo_modules.get_optimized_modules_dependencies(restrict_path)
    formatted_print(modules)


@cli.command(name='module_to_update')
@click.pass_context
def module_to_update(ctx):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    modules = odoo_modules.get_modules_to_update()
    formatted_print(modules)


@cli.command(name='module_to_remove')
@click.pass_context
def module_to_remove(ctx):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    modules = odoo_modules.get_modules_to_remove()
    formatted_print(modules)


@cli.command(name='installed_modules')
@click.option('--no-dependency', '-N', is_flag=True, help='Includes only modules without dependencies')
@click.pass_context
def installed_modules(ctx, no_dependency=False):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    modules = odoo_modules.get_installed_modules(only_leaves=no_dependency)
    formatted_print(modules)


@cli.command(name='diff')
@click.option('--to-database', '-t')
@click.pass_context
def diff(ctx, to_database):
    database = ctx.obj['database']
    from_modules = OdooModules(database)
    to_modules = OdooModules(to_database)
    diff_modules = from_modules.difference(to_modules)
    formatted_print(diff_modules)


if __name__ == '__main__':
    cli(obj={})
