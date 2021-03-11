import ast
import os
import re
from os.path import join as opj
from subprocess import Popen, PIPE

import pygraphviz
import networkx as nx
import csv

MANIFEST_FILES = ["__manifest__.py", "__openerp__.py"]
ADDONS_PATHES = [
    "./odoo/src/addons",
    "./odoo/src/odoo/addons",
    "./odoo/external-src",
    "./odoo/local-src"
]


def get_modules_pathes(addons_pathes=None, depth=2):
    if addons_pathes is None:
        addons_pathes = ADDONS_PATHES
    modules_pathes = {}
    for path in addons_pathes:
        if os.path.isfile(path) or not depth:
            return []
        files = os.listdir(path)
        for f in files:
            if os.path.isfile(os.path.join(path, f)) and f in MANIFEST_FILES:
                modules_pathes[os.path.basename(path)] = path
        for d in files:
            new_path = os.path.join(path, d)
            if os.path.isdir(new_path):
                modules_pathes.update(get_modules_pathes([new_path], depth-1))
    return modules_pathes


def module_manifest(path):
    """ Returns path to module manifest if one can be found under `path`,
    else `None`.
    """
    if not path:
        return None
    for manifest_name in MANIFEST_FILES:
        returned_path = opj(path, manifest_name)
        if os.path.isfile(returned_path):
            return returned_path
    return None


def to_native(source, encoding="utf-8", falsy_empty=False):
    if not source and falsy_empty:
        return ""

    if isinstance(source, bytes):
        return source.decode(encoding)

    return str(source)


def load_from_docker_psql(database="odoodb"):
    docker_cmd = "docker-compose run --rm odoo psql"
    sql_query = "select p.name, p.state, p.license, p.application, c.name, c.state, c.license, c.application from ir_module_module as p JOIN ir_module_module_dependency as r ON r.name = p.name JOIN ir_module_module as c ON c.id = r.module_id"
    proc = Popen([
        "{} -P pager=off --csv -t -d {} -c '{}'".format(
            docker_cmd, database, sql_query
        )
    ], stdout=PIPE, shell=True)
    output = proc.stdout.read()
    modules = {}
    for line in csv.reader(output.decode("utf-8").splitlines(), delimiter=","):
        if not re.compile("[_a-z]+").match(line[0]):
            # pre lines from output, does not contains any module
            continue
        (
            parent_name,
            parent_state,
            parent_license,
            parent_application,
            child_name,
            child_state,
            child_license,
            child_application,
        ) = line
        module = modules.get(parent_name, {
            "database_state": parent_state,
            "license": parent_license,
            "application": parent_application == "t",
            "children": [],
        })
        if child_name not in module["children"]:
            module["children"].append(child_name)
            sub_module_values = {
                "database_state": child_state,
                "license": child_license,
                "application": child_application == "t",
                "children": [],
            }
            sub_module = modules.get(child_name, sub_module_values)
            modules.update({child_name: sub_module})

        modules.update({parent_name: module})

    # with open("database_modules.json", "w") as a_file:
    #     json.dump(dict(sorted(modules.items())), a_file)
    return modules


def update_from_manifest(
        modules={},
        addons_paths=None
):
    # Load everything now
    # First all the manifest files per local modules
    if addons_paths is None:
        addons_paths = ADDONS_PATHES

    for child_name, path in get_modules_pathes(addons_paths, depth=2).items():
        manifest_file = module_manifest(path)
        # default values for descriptor
        info = {
            "application": False,
            "author": "Odoo S.A.",
            "auto_install": False,
            "category": "Uncategorized",
            "depends": [],
            "description": "",
            "installable": False,
            "license": "LGPL-3",
            "post_load": None,
            "version": "1.0",
            "web": False,
            "website": "https://www.odoo.com",
            "sequence": 100,
            "summary": "",
            "data": None,
            "demo": None,
            "test": None,
            "init_xml": None,
            "update_xml": None,
            "demo_xml": None,
        }

        if manifest_file:
            with open(manifest_file, mode="rb") as f:
                try:
                    content = f.read()
                    utf_8_converted = to_native(content)
                    evaluated = ast.literal_eval(utf_8_converted)
                    info.update(evaluated)
                finally:
                    f.close()

                if "active" in info:
                    # "active" has been renamed "auto_install"
                    info["auto_install"] = info["active"]

        state = States.UNINSTALLABLE
        if info["installable"] or info["auto_install"]:
            state = States.INSTALLABLE

        child_module = modules.get(child_name, {
            "children": []
        })
        child_state = child_module.get("state", False)
        child_module.update({
            # We do not override the database state
            "manifest_state": state if not child_state else child_state,
            "license": info["license"],
            "application": info["application"],
            "category": info["category"],
            "submodule": os.path.dirname(manifest_file),
        })

        modules.update({child_name: child_module})
        for parent_name in info["depends"]:
            parent_module = modules.get(parent_name, {
                "children": []
            })
            parent_module["children"].append(child_name)
            modules.update({parent_name: parent_module})

    return modules


def leaves(graph):
    """ Return modules not in dependency of any other module

    @:parameter graph <pygraphviz.AGraph>
    @:returns list<string>
    """
    edge_nodes = [e[0] for e in graph.edges()]
    return list(filter(lambda m: m not in edge_nodes, graph.nodes()))


class States:

    TO_INSTALL = "to install"
    TO_UPGRADE = "to upgrade"
    TO_REMOVE = "to remove"
    INSTALLABLE = "installable"
    INSTALLED = "installed"
    UNINSTALLABLE = "uninstallable"
    UNINSTALLED = "uninstalled"

    state2color = {
        TO_INSTALL: ("green", "black"),
        TO_UPGRADE: ("orange", "black"),
        TO_REMOVE: ("red", "black"),
        INSTALLED: ("white", "black"),
        INSTALLABLE: ("blue", "black"),
        UNINSTALLED: ("grey", "white"),
        UNINSTALLABLE: ("lightgrey", "white"),
    }
    state2group = {
        TO_INSTALL: "install",
        TO_UPGRADE: "upgrade",
        TO_REMOVE: "remove",
        INSTALLED: "installed",
        INSTALLABLE: "installable",
        UNINSTALLABLE: "uninstallable",
        UNINSTALLED: "uninstalled",
    }

    # (database state + manifest state) -> resulting state
    __state_mapper = {
        (False, False): UNINSTALLABLE,
        (INSTALLED, UNINSTALLABLE): TO_REMOVE,
        (INSTALLABLE, UNINSTALLABLE): UNINSTALLABLE,
        (UNINSTALLABLE, INSTALLABLE): INSTALLABLE,
        (TO_INSTALL, UNINSTALLABLE): UNINSTALLABLE,
        (TO_UPGRADE, UNINSTALLABLE): UNINSTALLABLE,
    }

    @staticmethod
    def merge(db_state, code_state):
        """

        :param db_state: State in database
        :param code_state: State in manifest
        :return:
        """
        if not code_state:
            return States.UNINSTALLABLE
        result = States.__state_mapper.get((db_state, code_state), db_state)
        if not result:
            return States.TO_REMOVE
        return result


class OdooModules:
    """ https://pythonhosted.org/OERPLib/tutorials.html#inspect-the-metadata-of-your-server-new-in-version-0-8

    """

    _database = None
    _exclude_states = set()
    _exclude_modules = set()
    _exclude_test_module = True
    _graph = None
    _modules = {}

    def __init__(
            self,
            database,
            exclude_modules=(),
            exclude_states=(),
            include_test_module=False
    ):
        assert (
            all([s for s in exclude_states if s in States.state2color.keys()]))
        self._database = database

        # Then priority to load the database
        # Then process manifest files (contains real code values to be applied)
        self._modules = load_from_docker_psql(self._database)
        update_from_manifest(self._modules)

        # Process resulting states and inconsistency
        for module_name in self._modules.keys():
            self._modules[module_name]["state"] = self._get_state(module_name)

        # with open("modules.json", "w") as a_file:
        #     json.dump(dict(sorted(self._modules.items())), a_file)

        self._graph = self._generate_pygraphviz(
            exclude_modules=exclude_modules,
            exclude_states=exclude_states,
            include_test_module=include_test_module
        )

    def _get_state(self, name):
        """ Returns the final state of a module depending of it"s state in
        database and manifest """
        if name not in self._modules.keys():
            return None
        database_state = self._modules[name].get("database_state", False)
        manifest_state = self._modules[name].get("manifest_state", False)
        result = States.merge(database_state, manifest_state)
        if not result:
            raise Exception("Inconsistent states db:{} manifest:{}".format(
                database_state, manifest_state
            ))
        return result

    def _check(self, name, raise_exception=True):
        """ Check if a module is present

        @:parameter raise_exception <bool> Raises an exception if not found
        @:raises <ModuleNotFoundError> if module is absent
        @:returns <bool>
        """
        if name not in self._graph.nodes():
            if raise_exception:
                raise ModuleNotFoundError(name)
            return False
        return True

    #
    # Delegated methods
    #

    def _lowest_common_ancestors(self, graph, names=None, states=None, index=0):
        """ Recursively return the lowest common ancestor of this modules list

        @:parameter graph <pygraphviz.AGraph>
        @:parameter names list<string> (A module names list)
        @:parameter states list<string> (A state list to filter)
        @:returns list<string>
        """
        if states is None:
            states = []
        nx_digraph = nx.DiGraph(graph)
        if not names:
            names = leaves(self._graph)
        lca = names[0]
        sorted_modules = set(sorted(names[index:]))
        if states:
            sorted_modules = filter(
                lambda m: self._get_state(m) in states,
                sorted_modules
            )
        for next, name in enumerate(sorted_modules):
            next_name = names[
                next] if next in names else None
            if not next_name:
                return names
            lca = nx.algorithms.lowest_common_ancestor(
                nx_digraph, lca, next_name
            )
            if lca:
                if lca == "base":
                    return [lca]
                del names[next]
            else:
                names = self._lowest_common_ancestors(
                    nx_digraph, names, states, next + 1
                )
        return names

    def _propagate_state_to_successors(self, graph, name):
        state = self._get_state(name)
        for child in graph.successors(name):
            if state == States.TO_REMOVE:
                self._modules[child]["state"] = state
            if state == "to update":
                self._modules[child]["state"] = state

    def _check_state_from_predecessors(self, graph, name):
        state = self._get_state(name)
        for child in graph.predecessors(name):
            if state != States.TO_INSTALL:
                continue
            child_state = self._get_state(child)
            if child_state not in (States.UNINSTALLABLE, States.TO_REMOVE):
                continue
            raise Exception(
                "'{}' parent's state is incompatible with state '{}'".format(
                    name, state
                )
            )

    def _add_node(self, graph, name, values):
        state = self._get_state(name)
        if not graph.has_node(name):
            graph.add_node(
                name,
                style="filled",
                color=States.state2color[state][1],
                fillcolor=States.state2color[state][0],
                group=States.state2group[state],
            )
        for child_name in values.get("children", []):
            graph.add_edge(name, child_name)
        return graph

    @staticmethod
    def _remove_node(graph, node):
        """ Removing a node implies to remove everything related: node and edges
            Then reconstructs all edges from predecessors to successors:
                node(edge(n), edge(m)) implies edge(n*m)
        """
        if graph.has_node(node):
            # Keep dependencies
            predecessors = graph.predecessors(node)
            successors = graph.successors(node)
            # Purge node and edges
            graph.remove_node(node)
            for edge in graph.edges(node):
                graph.remove_edge(edge.source, edge.target)
            # Then reconstructs all edges
            for (p, s) in zip(predecessors, successors):
                graph.add_edge(p, s)
        return graph

    def _generate_pygraphviz(
            self,
            exclude_modules=None,
            exclude_states=None,
            include_test_module=False,
    ):
        if exclude_states is None:
            exclude_states = []
        if exclude_modules is None:
            exclude_modules = []
        graph = pygraphviz.AGraph(
            strict=True,
            directed=True,
            pad="4",
            rankdir="LR",
            ranksep="4",
            overlap=False,
            splines="true"
        )

        for name, values in self._modules.items():
            # Populate the graph entirely (we need all original edges and nodes)
            self._add_node(graph, name, values)

        for name in graph.nodes():
            if (
                    name in exclude_modules
                    or self._get_state(name) in exclude_states
                    or (not include_test_module and name.startswith("test_"))
            ):
                self._remove_node(graph, name)

        # And clean it up from transitive edges
        graph.tred(copy=False)
        # Improve layout aspect ratio
        graph.unflatten(args="-l 6 -f -c 100")
        # Removes any cyclic dependencies
        graph.acyclic()

        # for name in graph.nodes():
        #     self._check_state_from_predecessors(graph, name)
        return graph

    def _create_root_subgraph(self, graph, name):
        """ Returns a sub graph with module as root node

        @:parameter graph <pygraphviz.AGraph>
        @:parameter name <string> (A module name)
        @:returns <DiGraph>
        """
        edges = nx.dfs_successors(nx.DiGraph(graph), name)
        nodes = set([])
        if self._exclude_states:
            for node in edges.keys():
                state = self._get_state(node)
                if state not in self._exclude_states:
                    nodes.add(node)
            for subnodes in edges.values():
                for node in subnodes:
                    state = self._get_state(node)
                    if state not in self._exclude_states:
                        nodes.add(node)
        else:
            for k, v in edges.items():
                nodes.add(k)
                nodes.update(v)
        return self._graph.subgraph(nodes)

    def _sub_graph_from_states(self, graph, states=None):
        """ Returns a subgraph for all module for state in `states`

        @:parameter states list<string> (A list of states)
        @:returns <pygraphviz.AGraph>
        """
        if states is None:
            states = []
        modules_to_remove = [
            name for name in self._modules.keys()
            if self._get_state(name) not in states
        ]
        sub_graph = graph.copy()
        for name in modules_to_remove:
            self._remove_node(sub_graph, name)
        return sub_graph

    #
    # Builtin functions
    #

    def __hash__(self):
        return self._modules.__hash__()

    def __eq__(self, other):
        if isinstance(other, OdooModules):
            return (
                self._modules.__eq__(other._modules)
                and self._exclude_states.__eq__(other._exclude_states)
                and self._exclude_test_module.__eq__(other._exclude_test_module)
                and self._exclude_modules.__eq__(other._exclude_modules)
                and self._database.__eq__(other._database)
            )
        return False

    #
    # Public API
    # DO NOT USE IN PRIVATE METHODS
    #

    def get_dependencies(self, name):
        """ Returns the dependency list of a module

        @:parameter name string (A module name)
        @:returns list<string> (A module names list)
        @:raise ModuleNotFoundError
        """
        self._check(name)
        subgraph = self._create_root_subgraph(self._graph, name)
        return [node for node in subgraph.nodes()]

    def get_state(self, name):
        """ Returns the actual state of a module

        @:parameter name string (A module name)
        @:returns <string> (A module state)
        @:raise ModuleNotFoundError
        """
        self._check(name)
        return self._modules[name]["state"]

    def modules(self):
        """ Return full modules list

        @:returns list<string> (A module names list)
        """
        return self._graph.nodes()

    def leaves(self):
        """ Return modules not in dependency of any other module

        @:returns list<string> (A module names list)
        """
        modules = leaves(self._graph)
        return modules

    def get_optimized_modules_dependencies(self, path=None):
        """ Returns the diff between actual dependencies and optimized ones

        :param path: restrict to a specific submodules
        :return:
        """
        diff = {}
        relpath = os.path.relpath(path, ".")
        for module, values in self._modules.items():
            has_submodule = "submodule" in values and values["submodule"]
            if not self._check(module, raise_exception=False):
                continue
            common_path = False
            if has_submodule:
                relsubpath = os.path.relpath(values["submodule"], ".")
                common_path = relpath in relsubpath
            if not common_path:
                continue
            children = [
                m for m, v in self._modules.items()
                if module in v["children"]
            ]
            predecessors = self._graph.predecessors(module)
            if set(predecessors) != set(children):
                diff[module] = {
                    "actual": sorted(children),
                    "optimized": sorted(predecessors),
                }
        return dict(sorted(diff.items()))

    def get_modules_to_update(self):
        """ Returns the shortest list of modules to update"""
        states = [States.TO_UPGRADE]
        graph = self._sub_graph_from_states(self._graph, states=states)
        modules = leaves(graph)
        lcas = self._lowest_common_ancestors(graph, modules, states=states)
        return sorted(lcas)

    def get_modules_to_install(self):
        """ Returns the shortest list of modules to install"""
        states = [States.TO_INSTALL]
        graph = self._sub_graph_from_states(self._graph, states=states)
        modules = leaves(graph)
        return sorted(modules)

    def get_modules_to_remove(self):
        """ Returns the shortest list of modules to remove"""
        states = [States.TO_REMOVE]
        graph = self._sub_graph_from_states(self._graph, states=states)
        modules = leaves(graph)
        lcas = self._lowest_common_ancestors(graph, modules, states=states)
        return sorted(lcas)

    def get_installed_modules(self, only_leaves=False):
        modules = [m for m, v in self._modules.items() if v["state"] == States.INSTALLED]
        if only_leaves:
            modules = [m for m in modules if m in self.leaves()]
        return sorted(modules)

    def save_as(self, filename="modules_dependency_graph-{}.png"):
        """ Save the module dependencies graphically

        Allowed file extensions:
            "canon", "cmap", "cmapx", "cmapx_np", "dia", "dot",
            "fig", "gd", "gd2", "gif", "hpgl", "imap", "imap_np",
            "ismap", "jpe", "jpeg", "jpg", "mif", "mp", "pcl", "pdf",
            "pic", "plain", "plain-ext", "png", "ps", "ps2", "svg",
            "svgz", "vml", "vmlz", "vrml", "vtx", "wbmp", "xdot", "xlib"

        @:parameter filename <string>
        @:returns <OdooModule>
        @:raise ModuleNotFoundError
        """
        allowed_extensions = [
            "canon", "cmap", "cmapx", "cmapx_np", "dia", "dot",
            "fig", "gd", "gd2", "gif", "hpgl", "imap", "imap_np",
            "ismap", "jpe", "jpeg", "jpg", "mif", "mp", "pcl", "pdf",
            "pic", "plain", "plain-ext", "png", "ps", "ps2", "svg",
            "svgz", "vml", "vmlz", "vrml", "vtx", "wbmp", "xdot", "xlib"
        ]
        name, extension = os.path.splitext(filename)
        if extension.replace(".", "") in allowed_extensions:
            self._graph.layout(prog="dot", args="-Nshape=box")
            self._graph.draw(filename.format(self._database))
            return self
        raise Exception("Extension not allowed!")
