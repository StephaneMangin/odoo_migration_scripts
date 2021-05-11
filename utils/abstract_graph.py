#!/usr/bin/env python

import os

import pygraphviz
import networkx as nx

from . import add_node, clean_graph, check_node, leaves


class AbstractGraph:

    _name = None
    _nodes = {}
    _graph = None
    _exclude_nodes = []

    def __init__(
            self,
            name,
            exclude_nodes=(),
            **kwargs
    ):
        self._name = name
        self._exclude_nodes = exclude_nodes
        self._nodes = self._load_nodes(**kwargs)
        self._graph = self._generate_pygraphviz(exclude_nodes=exclude_nodes)

    #
    # Delegated methods
    #

    def _load_nodes(self, **kwargs):
        raise NotImplemented

    def _lowest_common_ancestors(self, graph, names=None, exclude_nodes=None, index=0):
        """ Recursively return the lowest common ancestor of this nodes list

        @:parameter graph <pygraphviz.AGraph>
        @:parameter names list<string> (A node names list)
        @:parameter states list<string> (A state list to filter)
        @:returns list<string>
        """
        nx_digraph = nx.DiGraph(graph)
        if not names:
            names = leaves(graph)
        lca = names[0]
        sorted_nodes = set(sorted(names[index:]))
        if exclude_nodes:
            sorted_nodes = sorted_nodes.difference(exclude_nodes)
        for next, name in enumerate(sorted_nodes):
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
                    nx_digraph, names, exclude_nodes, next + 1
                )
        return names

    def _generate_pygraphviz(
            self,
            exclude_nodes=None,
            lambda_color_fillcolor_group=lambda node, values: (None, None, None)
    ):
        if exclude_nodes is None:
            exclude_nodes = []
        graph = pygraphviz.AGraph(
            strict=True,
            directed=True,
            pad="4",
            rankdir="LR",
            ranksep="4",
            overlap=False,
            splines="true"
        )
        for name, values in self._nodes.items():
            # Populate the graph entirely (we need all original edges and nodes)
            color, fillcolor, group = lambda_color_fillcolor_group(name, values)
            add_node(graph, name, values, color, fillcolor, group)
        # _clean_graph(graph)
        return graph

    def _create_root_subgraph(self, graph, name):
        """ Returns a sub graph with node as root node

        @:parameter graph <pygraphviz.AGraph>
        @:parameter name <string> (A node name)
        @:returns <DiGraph>
        """
        edges = nx.dfs_successors(nx.DiGraph(graph), name)
        nodes = set([])
        for k, v in edges.items():
            nodes.add(k)
            nodes.update(v)
        graph = self._graph.subgraph(nodes)
        clean_graph(graph)
        return graph

    #
    # Builtin functions
    #

    def __hash__(self):
        return self._nodes.__hash__()

    #
    # Public API
    # DO NOT USE IN PRIVATE METHODS
    #

    def get_dependencies(self, name):
        """ Returns the dependency list of a node

        @:parameter name string (A node name)
        @:returns list<string> (A node names list)
        @:raise nodeNotFoundError
        """
        check_node(self._graph, name)
        subgraph = self._create_root_subgraph(self._graph, name)
        return [node for node in subgraph.nodes()]

    def nodes(self):
        """ Return full nodes list

        @:returns list<string> (A node names list)
        """
        return self._graph.nodes()

    def leaves(self):
        """ Return nodes not in dependency of any other node

        @:returns list<string> (A node names list)
        """
        nodes = leaves(self._graph)
        return nodes

    def difference(self, abstract_graph):
        """ Returns a dict representing differences between two Odoo nodes

        :param abstract_graph: <AbstractGraph>
        :return:
        """
        old_nodes = set(self.nodes())
        new_nodes = set(abstract_graph.nodes())
        intersection = new_nodes.intersection(old_nodes)
        old_difference = old_nodes.difference(new_nodes)
        new_difference = new_nodes.difference(old_nodes)
        return {
            "removed": sorted(list(old_difference - intersection)),
            "added": sorted(list(new_difference - intersection)),
        }

    def save_as(self, filename="nodes_dependency_graph-{}.png", dpi=None):
        """ Save the node dependencies graphically

        Allowed file extensions:
            "canon", "cmap", "cmapx", "cmapx_np", "dia", "dot",
            "fig", "gd", "gd2", "gif", "hpgl", "imap", "imap_np",
            "ismap", "jpe", "jpeg", "jpg", "mif", "mp", "pcl", "pdf",
            "pic", "plain", "plain-ext", "png", "ps", "ps2", "svg",
            "svgz", "vml", "vmlz", "vrml", "vtx", "wbmp", "xdot", "xlib"

        @:parameter filename <string>
        @:returns <Odoonode>
        @:raise nodeNotFoundError
        """
        allowed_extensions = [
            "canon", "cmap", "cmapx", "cmapx_np", "dia", "dot",
            "fig", "gd", "gd2", "gif", "hpgl", "imap", "imap_np",
            "ismap", "jpe", "jpeg", "jpg", "mif", "mp", "pcl", "pdf",
            "pic", "plain", "plain-ext", "png", "ps", "ps2", "svg",
            "svgz", "vml", "vmlz", "vrml", "vtx", "wbmp", "xdot", "xlib"
        ]
        name, extension = os.path.splitext(filename)
        args = ""
        if dpi:
            args += f"-Gdpi={dpi}"
        if extension.replace(".", "") in allowed_extensions:
            self._graph.layout(prog="dot", args="-Nshape=box")
            self._graph.draw(filename.format(self._name), args=args)
            return self
        raise Exception("Extension not allowed!")
