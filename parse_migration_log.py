#!/usr/bin/env python

import time
import os

"""
    Parse and returns a dict of all errors prone lines

    Usage:
        $ parse_migration_log my_file.log
        or with implied log file as "./database_migration.log"
        $ parse_migration_log

    Returns:
        {
            'module': {
                'to_install': [],
                'to_uninstall': [],
                'remove_from_uninstaller': [],
                'autoinstalled': [],
            },
            'constraints': {
                sql_name: sql_type,
            },
            'invalid_modules': [
                module_name,
            ],
            'drop_table_dependencies': {
                table_name: {
                    table_child_name: table_constraint_name,
                }
            },
            'columns_missing': {
                column_name: {
                    column_name: [
                        line_no,
                    ]
                },
                'no_table': {
                    column_name: [
                        line_no,
                    ]
                },
            },
            'relations_missing': {
                relation_name: [
                    line_no1,
                    line_no2,
                ]
            },
            'fields_load_failed': {
                table_name: {
                    column_name,
                },
            },
            'metadata_left': []
            'migration_step_duration': {
                "parent step":
                    [
                        "text: duration in sec",
                    ]
            }
        }

"""
import re
import json

DEFAULT_LOGFILE = "database_migration.log"
UNINSTALLER_FILE = "./odoo/songs/migration/uninstall.py"
MIGRATION_FILE = "odoo/migration.yml"
NAME_PATTERN_VAR = r"([a-zA-Z_ ]*)"
MODULE_PATTERN_VAR = r"([a-z_]*)"

DROP_PATTERN = r"sql_db: bad query: DROP TABLE \"" + NAME_PATTERN_VAR + "\""
MODULE_LOAD_PATTERN = r"Some modules are not loaded, some dependencies or manifest may be missing: (\[.*\])"
MODULE_STATE_PATTERN = r"Some modules have inconsistent states, some dependencies may be missing: (\[.*\])"
DROP_TABLE_ATTEMPT_PATTERN = r"Start purging tables attempt n°"
DROP_DETAILS_LINE_PATTERN = "constraint " + NAME_PATTERN_VAR + " on table " + NAME_PATTERN_VAR + " depends on table " + NAME_PATTERN_VAR + ""
DROP_HINT_PATTERN = "HINT:"
TABLE_PATTERN = r"Table '" + NAME_PATTERN_VAR + "': unable to "
COLUMN_PATTERN = r"set " + NAME_PATTERN_VAR + " on column '" + NAME_PATTERN_VAR + "'"
COLUMN_PATTERN = r"set " + NAME_PATTERN_VAR + " on column '" + NAME_PATTERN_VAR + "'"
CONSTRAINT1_PATTERN = r"add constraint '" + NAME_PATTERN_VAR + "' as ([a-zA-Z_ ]*\(.*\))"
CONSTRAINT2_START_PATTERN = r"add constraint '" + NAME_PATTERN_VAR + "' as CHECK\($"
CONSTRAINT2_END_PATTERN = r"            \)"
COLUMN_MISSING_PATTERN = r"(psycopg2\.ProgrammingError|ERROR): column " + NAME_PATTERN_VAR + "." + NAME_PATTERN_VAR + " does not exist"
COLUMN_MISSING_PATTERN2 = r"ERROR:  column \"" + NAME_PATTERN_VAR + "\" does not exist"
COLUMN_MISSING_PATTERN3 = r"ERROR:  column \"" + NAME_PATTERN_VAR + "\" of relation \"" + NAME_PATTERN_VAR + "\" does not exist"
RELATION_MISSING_PATTERN = r"ERROR:  relation \"" + NAME_PATTERN_VAR + "\" does not exist"
FIELD_LOAD_PATTERN = r"ir_model: Failed to load field " + NAME_PATTERN_VAR + "." + NAME_PATTERN_VAR + "." + NAME_PATTERN_VAR + ": skipped"
METADATA_PATTERN = r"===> CAN'T UNLINK MODULE, WE HAVE METADATA"
METADATA_MODULE_PATTERN = r"MODULE UNAVAILABLE \(will be deleted\) : ([a-z0-9_]*)"
BAD_STATE_MODULE_PATTERN = r"MODULE UNAVAILABLE BUT BAD STATE : ([a-z0-9_]*) \(([a-z_ ]*)\)"
MIGRATION_VERSION_PATTERN = r"    - version: ([a-z0-9_]*)(.*)"
MIGRATION_UPGRADE_PATTERN = r"        upgrade:"
MIGRATION_MODULE_PATTERN = r"          - " + MODULE_PATTERN_VAR + ""
STEP_MIGRATION_DURATION = r"(.*): ([0-9]*.[0-9]*)s"

ALL_MODULES_BY_PATH = {}

RESULTS = {
    '_durations': "",
    'modules': {
        'to_install': {},
        'remove_from_uninstaller': [],
        'autoinstalled': [],
        'bad_state': [],
        'metadata_left': [],
        'invalid': [],
    },
    'constraints': {},
    'drop_table_dependencies': {},
    'columns_missing': {},
    'relations_missing': {},
    'fields_load_failed': {},
    'migration_step_duration': {},
}


def timeit(method):
    def timed(*args, **kw):
        print("Start call for %s()" % (method.__qualname__))
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        print(" - End " + ' (%2.2f ms)' % ((te - ts) * 1000))
        return result

    return timed


for root in (
        './odoo/external-src',
        './odoo/src/addons',
        './odoo/src/odoo/addons',
        './odoo/local-src'):
    depth = 12
    for path, dirs, files in os.walk(root):
        print(path)
        if depth == 0:
            break
        for d in dirs:
            current_path = os.path.join(path, d)
            d_files = os.listdir(current_path)
            if '__manifest__.py' in d_files or '__openerp__.py' in d_files:
                ALL_MODULES_BY_PATH[d] = path
        depth -= 1


def _get_repo_from_module_name(module_name):
    for module, path in ALL_MODULES_BY_PATH.items():
        if module == module_name:
            return ALL_MODULES_BY_PATH[module_name]


def _check_find(line, patterns):
    for pattern in patterns:
        if pattern in line:
            return True
    return False


def _cut_at(lines, pattern, include_pattern=False):
    """ Cut a list at pattern matching and return first list reversed """
    if not lines:
        return []
    found_lines = []
    for index, line in enumerate(lines, 1):
        if pattern not in line:
            continue
        found_lines = lines[:index - (1 if include_pattern else 0)][::-1]

    return found_lines


def _get_lines_between(start_pattern, end_pattern, lines):
    """ Returns a list of lines between two line containing patterns
    """
    if not lines:
        return []
    return _cut_at(_cut_at(lines, start_pattern), end_pattern)


@timeit
def parse_invalid_modules(lines, result):
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(MODULE_LOAD_PATTERN, line)
            if not match:
                match = re.search(MODULE_STATE_PATTERN, line)
                if not match:
                    continue
            module_list = json.loads(match.group(1).replace("'", '"'))
            result.extend(module_list)
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_failed_constraints(lines, result):
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(TABLE_PATTERN, line)
            if not match:
                continue
            table_name = match.group(1)
            constraint1_match = re.search(CONSTRAINT1_PATTERN, line)
            constraint2_match = re.search(CONSTRAINT2_START_PATTERN, line)
            column_match = re.search(COLUMN_PATTERN, line)

            if table_name not in result:
                result[table_name] = {}

            if constraint1_match:
                constraint_name = constraint1_match.group(1)
                code = constraint1_match.group(2)
                result[table_name][constraint_name] = code

            elif constraint2_match:
                constraint_name = constraint2_match.group(1)
                code = "CHECK("
                current_line_no = index + 1
                current_line = lines[current_line_no]
                while not re.match(CONSTRAINT2_END_PATTERN, current_line):
                    code += current_line
                    current_line_no += 1
                    current_line = lines[current_line_no]
                code += current_line
                result[table_name][constraint_name] = code.replace("\n\n", "\n")
                result[table_name][constraint_name] = code.replace("\n\n", "\n")

            elif column_match:
                column_name = column_match.group(2)
                type_name = column_match.group(1)
                if column_name not in result[table_name]:
                    result[table_name][column_name] = []
                if type_name not in result[table_name][column_name]:
                    result[table_name][column_name] += [type_name]
                result[table_name][column_name] = sorted(
                    result[table_name][column_name])

            else:
                result[table_name]['unknown'] = line
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_missing_columns(lines, result):
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(COLUMN_MISSING_PATTERN, line)

            if match:
                table_name = match.group(2)
                column_name = match.group(3)
                if table_name and table_name not in result:
                    result[table_name] = {}
                if column_name not in result[table_name]:
                    result[table_name].update({column_name: [index]})
                if index not in result[table_name][column_name]:
                    result[table_name][column_name] += [index]
                result[table_name][column_name] = sorted(
                    result[table_name][column_name])

            match2 = re.search(COLUMN_MISSING_PATTERN2, line)
            if match2:
                column_name = match2.group(1)
                if 'no_table' not in result:
                    result['no_table'] = {}
                if column_name not in result['no_table']:
                    result['no_table'].update({column_name: [index]})
                if index not in result['no_table'][column_name]:
                    result['no_table'][column_name] += [index]
                result['no_table'][column_name] = sorted(
                    result['no_table'][column_name])

            match3 = re.search(COLUMN_MISSING_PATTERN3, line)
            if match3:
                table_name = match3.group(2)
                column_name = match3.group(1)
                if table_name and table_name not in result:
                    result[table_name] = {}
                if column_name not in result[table_name]:
                    result[table_name].update({column_name: [index]})
                if index not in result[table_name][column_name]:
                    result[table_name][column_name] += [index]
                result[table_name][column_name] = sorted(
                    result[table_name][column_name])
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_missing_relations(lines, result):
    for index, line in enumerate(lines, 1):
        if "marabunta_version" in line:
            continue
        try:
            match = re.search(RELATION_MISSING_PATTERN, line)
            if match:
                relation_name = match.group(2)
                if relation_name and relation_name not in result:
                    result[relation_name] = []
                if index not in result[relation_name]:
                    result[relation_name] += [index]
                result[relation_name] = sorted(result[relation_name])

        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_failed_fields_load(lines, result):
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(FIELD_LOAD_PATTERN, line)
            if not match:
                continue
            if match:
                view_name = match.group(1)
                table_name = match.group(2)
                column_name = match.group(3)
                if view_name and view_name not in result:
                    result[view_name] = {}
                if table_name and table_name not in result[view_name]:
                    result[view_name][table_name] = []
                if column_name not in result[view_name][table_name]:
                    result[view_name][table_name] += [column_name]
                result[view_name][table_name] = sorted(result[view_name][table_name])
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_drop_table_dependencies(lines, result):
    """ Avoid false positive as this process act several times before
    completion.
    We only treat the last attempt """

    def parse_line(lines, result):
        for index, line in enumerate(drop_table_lines, 1):
            try:

                attempt = re.search(DROP_TABLE_ATTEMPT_PATTERN, line)
                # For each attempt we reset the result to avoid true negative
                if attempt:
                    result = {}

                match = re.search(DROP_PATTERN, line)
                if not match:
                    continue
                drop_name = match.group(1)
                if drop_name and drop_name not in result:
                    result[drop_name] = {}

                current_line_no = index + 3  # we jump to DETAILS line ()
                current_line = lines[current_line_no]
                while not re.match(DROP_HINT_PATTERN, current_line):
                    table_child_match = re.search(DROP_DETAILS_LINE_PATTERN,
                                                  current_line)
                    if table_child_match:
                        table_child_name = table_child_match.group(2)
                        table_constraint_name = table_child_match.group(1)
                        if table_child_name not in result[drop_name]:
                            result[drop_name].update(
                                {table_child_name: table_constraint_name})
                    current_line_no += 2  # we jump to next DETAILS line
                    try:
                        current_line = lines[current_line_no]
                    except IndexError:
                        # End of lines
                        break

            except Exception as e:
                print(e)
                print("Error on line {}: \"{}\"".format(index, line))

    drop_table_lines = _get_lines_between(
        "Clean models data from uninstalled modules....",
        "Start purging tables attempt n°",
        lines,
    )
    parse_line(drop_table_lines, result)


@timeit
def parse_metadata_left(lines, result):
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(METADATA_PATTERN, line)
            if not match:
                continue
            previous_index = index - 3
            previous_line = lines[previous_index]
            match = re.search(METADATA_MODULE_PATTERN, previous_line)
            if match:
                module_name = match.group(1)
                result.append(module_name)
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_bad_state_left(lines, result):
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(BAD_STATE_MODULE_PATTERN, line)
            if not match:
                continue
            if match:
                module_name = match.group(1)
                state_name = match.group(2)
                result.append((module_name, state_name))
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))


@timeit
def parse_migration_step_duration(lines, result):
    parent_content = []
    total_duration = .0
    for index, line in enumerate(lines, 1):
        try:
            match = re.search(STEP_MIGRATION_DURATION, line)
            if not match:
                continue
            text = match.group(1)
            duration = match.group(2)
            try:
                duration = float(duration)
                text = text.replace("    ", "\t")
                if text.count('\t') == 1:
                    parent_content.append("{}: {}s".format(text.lstrip("\t").rstrip(" ").lstrip(" "), duration))
                elif not text.count('\t'):
                    parent_line = "{}: {}s".format(text.lstrip("\t").rstrip(" ").lstrip(" "), duration)
                    if parent_line not in result:
                        result[parent_line] = parent_content
                        total_duration += duration
                    parent_content = []
            except:
                pass
        except Exception as e:
            print(e)
            print("Error on line {}: \"{}\"".format(index, line))
    result['total duration in min'] = total_duration / 60


if __name__ == '__main__':

    ## log parser
    if not os.path.exists(DEFAULT_LOGFILE):
        raise Exception(DEFAULT_LOGFILE + " couldn't be found !")
    with open(DEFAULT_LOGFILE, 'r') as file:
        lines = [line for line in file]
        # Specific treatment as this parse is dependant to start/end patterns
        parse_drop_table_dependencies(lines, RESULTS['drop_table_dependencies'])
        parse_failed_constraints(lines, RESULTS['constraints'])
        parse_missing_columns(lines, RESULTS['columns_missing'])
        parse_missing_relations(lines, RESULTS['relations_missing'])
        parse_failed_fields_load(lines, RESULTS['fields_load_failed'])
        parse_migration_step_duration(lines, RESULTS['migration_step_duration'])
        parse_metadata_left(lines, RESULTS['modules']['metadata_left'])
        parse_bad_state_left(lines, RESULTS['modules']['bad_state'])
        parse_invalid_modules(lines, RESULTS['modules']['invalid'])

    ## Modules parser
    all_modules_to_install = {}
    with open(MIGRATION_FILE, 'r') as file:
        lines = [line for line in file]
        version = False
        upgrades = False
        for line in lines:
            # match = re.search(MIGRATION_VERSION_PATTERN, line)
            # if match:
            #     version = match.group(1)
            #     upgrades = False
            #     continue
            match = re.search(MIGRATION_UPGRADE_PATTERN, line)
            if match:
                upgrades = True
                continue
            if upgrades:
                match = re.search(MIGRATION_MODULE_PATTERN, line)
                if match:
                    module_name = match.group(1)
                    repo_name = _get_repo_from_module_name(module_name)
                    if repo_name:
                        if repo_name not in all_modules_to_install:
                            all_modules_to_install[repo_name] = []
                        all_modules_to_install[repo_name].append(module_name)
                        all_modules_to_install[repo_name] = sorted(
                            set(all_modules_to_install[repo_name]))
                    else:
                        RESULTS['modules']['invalid'].append(module_name)
                        RESULTS['modules']['invalid'] = sorted(
                            set(RESULTS['modules']['invalid']))

    RESULTS['modules']['to_install'] = all_modules_to_install

    uninstall_module_list = []
    with open(UNINSTALLER_FILE, 'r') as file:
        content = '%%%'.join(
            [line.rstrip(', \r\n').lstrip(' ') for line in file])
        sub_content = content[content.find(
            "UNINSTALL_MODULES_LIST = [") + 1:content.find("]")]
        for line in sub_content.split("%%%"):
            if not line:
                continue
            match = re.search(r"'" + MODULE_PATTERN_VAR + "'", line)
            if not match:
                continue
            module_name = match.group(1)
            uninstall_module_list.append(module_name)

    RESULTS['modules']['remove_from_uninstaller'] = list(
        set(sum(all_modules_to_install.values(), []) + RESULTS['modules'][
            'invalid']).intersection(set(uninstall_module_list))
    )

    print(json.dumps(RESULTS, sort_keys=True, indent=4))
