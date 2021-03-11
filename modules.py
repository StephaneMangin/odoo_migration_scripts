#!/usr/bin/env python
import pprint

import click

from odoo_module_graph import OdooModules

pp = pprint.PrettyPrinter(indent=4)


@click.group()
@click.option('--database', "-d", help='Database name')
@click.pass_context
def cli(ctx, database):
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)
    ctx.obj['database'] = database


@cli.command(name='optimize_dependencies')
@click.option('--restrict-path', default="./odoo/local-src", help='A specific path to search modules from')
@click.pass_context
def optimize_dependencies(ctx, restrict_path):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    pp.pprint(odoo_modules.get_optimized_modules_dependencies(restrict_path))


@cli.command(name='module_to_update')
@click.pass_context
def module_to_update(ctx):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    pp.pprint(odoo_modules.get_modules_to_update())


@cli.command(name='module_to_remove')
@click.pass_context
def module_to_remove(ctx):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    pp.pprint(odoo_modules.get_modules_to_remove())


@cli.command(name='installed_modules')
@click.option('--no-dependency', '-N', is_flag=True, help='Includes only modules without dependencies')
@click.pass_context
def installed_modules(ctx, no_dependency):
    database = ctx.obj['database']
    odoo_modules = OdooModules(database)
    pp.pprint(odoo_modules.get_installed_modules(only_leaves=no_dependency))


if __name__ == '__main__':
    cli(obj={})
