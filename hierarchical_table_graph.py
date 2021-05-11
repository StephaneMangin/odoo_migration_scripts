#!/usr/bin/env python
import csv
from subprocess import Popen, PIPE

from utils import remove_node
from utils.abstract_graph import AbstractGraph


def load_from_docker_psql(database):
    docker_cmd = "docker-compose run --rm odoo psql"
    sql_query = "select p.id, p.name, p.key, p.website_id, c.id, c.name, c.key, c.website_id from ir_ui_view as p RIGHT JOIN ir_ui_view as c ON c.inherit_id = p.id"
    proc = Popen([
        "{} -P pager=off --csv -t -d {} -c '{}'".format(
            docker_cmd, database, sql_query
        )
    ], stdout=PIPE, shell=True)
    output = proc.stdout.read()
    modules = {}

    def view_to_keep(name, website_id):
        return bool(website_id) or "website_slx" in name.lower()

    for line in csv.reader(output.decode("utf-8").splitlines()[8:], delimiter=","):
        (
            parent_id,
            parent_name,
            parent_key,
            parent_website_id,
            child_id,
            child_name,
            child_key,
            child_website_id
        ) = line
        # print(line)

        p_name = '/'.join([str(parent_id), parent_key, parent_name])
        module = modules.get(p_name, {
            "id": parent_id,
            "name": parent_name,
            "key": parent_key,
            "to_keep": view_to_keep(parent_name, parent_website_id),
            "website_id": parent_website_id,
            "children": [],
        })
        if child_name not in module["children"]:
            c_name = '/'.join([str(child_id), child_key, child_name])
            module["children"].append(c_name)
            to_keep = view_to_keep(child_name, child_website_id)
            if to_keep:
                module["to_keep"] = True
            sub_module_values = {
                "id": child_id,
                "name": child_name,
                "key": child_key,
                "to_keep": to_keep,
                "website_id": child_website_id,
                "children": [],
            }
            sub_module = modules.get(c_name, sub_module_values)
            modules.update({c_name: sub_module})
        modules.update({p_name: module})
    for root_name in modules.keys():
        module = modules.get(root_name, {"children": []})
        if module["children"]:
            module["to_keep"] = _recurse_propagate_to_keep(modules, root_name)

    # print(json.dumps(modules))

    return modules


def _recurse_propagate_to_keep(modules, name, index=1):
    module = modules.get(name)
    # print("|   " * index + name)
    for child_name in modules.get(name, {"children": []})["children"]:
        to_keep = _recurse_propagate_to_keep(modules, child_name, index + 1)
        module["to_keep"] = to_keep or module["to_keep"]
    # if module["to_keep"]:
        # print("####" * index)
    return module["to_keep"]


class HierarchicalTable(AbstractGraph):

    def __init__(self, name, dbtable, parent_column="parent_id"):
        super().__init__(name, dbtable=dbtable, parent_column=parent_column)

    def _load_nodes(self, **kwargs):
        return load_from_docker_psql(self._name)

    @staticmethod
    def _get_cfg_from_node(name, values):
        color = None
        fillcolor = None
        if values["to_keep"]:
            color = "black"
            fillcolor = "blue"
        return color, fillcolor, None

    def nodes_to_keep(self):
        nodes = []
        for node, values in self._nodes.items():
            if values["to_keep"]:
                nodes.append(node)
                nodes.extend(self._graph.predecessors(node))
        return set(nodes)

    def _generate_pygraphviz(
            self,
            exclude_nodes=None,
            lambda_color_fillcolor_group=lambda name, values: (None, None, None)
    ):
        return super()._generate_pygraphviz(
            exclude_nodes=exclude_nodes,
            lambda_color_fillcolor_group=self._get_cfg_from_node
        )

    def remove_nodes(self, nodes):
        """ Removes a list of nodes """
        for node in nodes:
            remove_node(self._graph, node)


if __name__ == "__main__":
    graph = HierarchicalTable("odoodb_template", "ir_ui_view", "inherit_id")
    to_keep = set(graph.nodes_to_keep())
    ids_to_keep = [values["id"] for node, values in filter(lambda k: k[0] in to_keep, graph._nodes.items())]
    all_nodes = set(graph.nodes())
    to_remove = all_nodes.difference(to_keep)
    graph.remove_nodes(to_remove)
    print("All nodes {}".format(len(all_nodes)))
    print("Nodes to keep {}".format(len(to_keep)))
    print("Nodes ids to keep {}".format(len(ids_to_keep)))
    print("ids list to keep {}".format(ids_to_keep))
    print("Nodes to remove {}".format(len(all_nodes - to_keep)))
    graph.save_as()
