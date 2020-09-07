#!/usr/bin/env python

"""
    Parse and returns a dict of all errors prone lines

    Usage:
        $ parse_migration_log my_file.log
        or with implied log file as "./database_migration.log"
        $ parse_migration_log

    Returns:
        {
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
            'fields_load_failed': {
                table_name: {
                    column_name,
                },
            },
        }

"""
import re
import sys
import json

DEFAULT_LOGFILE = "database_migration.log"
NAME_PATTERN_VAR = r"([a-zA-Z_ ]*)"

DROP_PATTERN = r"sql_db: bad query: DROP TABLE \"" + NAME_PATTERN_VAR + "\""
MODULE_PATTERN = r"Some modules are not loaded, some dependencies or manifest may be missing: (\[.*\])"
DROP_DETAILS_LINE_PATTERN = "constraint " + NAME_PATTERN_VAR + " on table " + NAME_PATTERN_VAR + " depends on table " + NAME_PATTERN_VAR + ""
DROP_HINT_PATTERN = "HINT:"
TABLE_PATTERN = r"Table '" + NAME_PATTERN_VAR + "': unable to "
COLUMN_PATTERN = r"set $NAME_PATTERN_VAR on column '" + NAME_PATTERN_VAR + "'"
CONSTRAINT1_PATTERN = r"add constraint '" + NAME_PATTERN_VAR + "' as ([a-zA-Z_ ]*\(.*\))"
CONSTRAINT2_START_PATTERN = r"add constraint '" + NAME_PATTERN_VAR + "' as CHECK\($"
CONSTRAINT2_END_PATTERN = r"            \)"
COLUMN_MISSING_PATTERN = r"(psycopg2\.ProgrammingError|ERROR): column " + NAME_PATTERN_VAR + "." + NAME_PATTERN_VAR + " does not exist"
COLUMN_MISSING_PATTERN2 = r"ERROR:  column \"" + NAME_PATTERN_VAR + "\" does not exist"
COLUMN_MISSING_PATTERN3 = r"ERROR:  column \"" + NAME_PATTERN_VAR + "\" of relation \"" + NAME_PATTERN_VAR + "\" does not exist"
FIELD_LOAD_PATTERN = r"ir_model: Failed to load field " + NAME_PATTERN_VAR + "." + NAME_PATTERN_VAR + "." + NAME_PATTERN_VAR + ": skipped"


def parse_drop_table_dependencies(line, index, lines, result):
    match = re.search(DROP_PATTERN, line)
    if not match:
        return
    drop_name = match.group(1)
    if drop_name and drop_name not in result:
        result[drop_name] = {}

    dependencies = {}
    current_line_no = index + 3  # we jump to DETAILS line ()
    current_line = lines[current_line_no]
    while not re.match(DROP_HINT_PATTERN, current_line):
        table_child_match = re.search(DROP_DETAILS_LINE_PATTERN, current_line)
        table_child_name = table_child_match.group(2)
        table_constraint_name = table_child_match.group(1)
        if table_child_name not in result[drop_name]:
            result[drop_name].update({table_child_name: table_constraint_name})
        current_line_no += 2  # we jump to next DETAILS line
        current_line = lines[current_line_no]


def parse_invalid_modules(line, result):
    match = re.search(MODULE_PATTERN, line)
    if not match:
        return
    module_list = json.loads(match.group(1).replace("'", '"'))
    result = sorted([mod for mod in module_list if mod not in result])


def parse_constraints(line, index, lines, result):
    match = re.search(TABLE_PATTERN, line)
    if not match:
        return
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
        result[table_name][column_name] = sorted(result[table_name][column_name])

    else:
        result[table_name]['unknown'] = line


def parse_missing_columns(line, line_no, result):
    match = re.search(COLUMN_MISSING_PATTERN, line)
    match2 = re.search(COLUMN_MISSING_PATTERN2, line)
    match3 = re.search(COLUMN_MISSING_PATTERN3, line)
    if not match and not match2 and not match3:
        return
    if match:
        table_name = match.group(2)
        column_name = match.group(3)
        if table_name and table_name not in result:
            result[table_name] = {}
        if column_name not in result[table_name]:
            result[table_name].update({column_name: [line_no]})
        if line_no not in result[table_name][column_name]:
            result[table_name][column_name] += [line_no]
        result[table_name][column_name] = sorted(result[table_name][column_name])
    if match2:
        column_name = match2.group(1)
        if 'no_table' not in result:
            result['no_table'] = {}
        if column_name not in result['no_table']:
            result['no_table'].update({column_name: [line_no]})
        if line_no not in result['no_table'][column_name]:
            result['no_table'][column_name] += [line_no]
        result['no_table'][column_name] = sorted(result['no_table'][column_name])
    if match3:
        table_name = match3.group(2)
        column_name = match3.group(1)
        if table_name and table_name not in result:
            result[table_name] = {}
        if column_name not in result[table_name]:
            result[table_name].update({column_name: [line_no]})
        if line_no not in result[table_name][column_name]:
            result[table_name][column_name] += [line_no]
        result[table_name][column_name] = sorted(result[table_name][column_name])

def parse_fields_load(line, result):
    match = re.search(FIELD_LOAD_PATTERN, line)
    if not match:
        return
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


if __name__ == '__main__':
    logfile = sys.argv[1] if len(sys.argv) >= 2 else DEFAULT_LOGFILE
    RESULTS = {
        'constraints': {},
        'invalid_modules': [],
        'drop_table_dependencies': {},
        'columns_missing': {},
        'fields_load_failed': {},
    }
    with open(logfile, 'r') as file:
        lines = [line for line in file]
        for index, line in enumerate(lines, 1):
            try:
                parse_drop_table_dependencies(line, index, lines, RESULTS['drop_table_dependencies'])
                parse_invalid_modules(line, RESULTS['invalid_modules'])
                parse_constraints(line, index, lines, RESULTS['constraints'])
                parse_missing_columns(line, index, RESULTS['columns_missing'])
                parse_fields_load(line, RESULTS['fields_load_failed'])
            except Exception as e:
                print(e)
                print("Error on line {}: \"{}\"".format(index, line))

    print(json.dumps(RESULTS, sort_keys=True, indent=4))
