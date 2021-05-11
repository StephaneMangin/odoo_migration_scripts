#!/usr/bin/env python


def to_native(source, encoding="utf-8", falsy_empty=False):
    if not source and falsy_empty:
        return ""

    if isinstance(source, bytes):
        return source.decode(encoding)

    return str(source)


def leaves(graph):
    """ Return nodes not in dependency of any other node

    @:parameter graph <pygraphviz.AGraph>
    @:returns list<string>
    """
    edge_nodes = [e[0] for e in graph.edges()]
    return list(filter(lambda m: m not in edge_nodes, graph.nodes()))


def clean_graph(graph):
    # And clean it up from transitive edges
    graph.tred(copy=False)
    # Improve layout aspect ratio
    graph.unflatten(args="-l 6 -f -c 100")
    # Removes any cyclic dependencies
    graph.acyclic()


def check_node(graph, name, raise_exception=True):
    """ Check if a node is present

    @:parameter raise_exception <bool> Raises an exception if not found
    @:raises <nodeNotFoundError> if node is absent
    @:returns <bool>
    """
    if name not in graph.nodes():
        if raise_exception:
            raise Exception(name)
        return False
    return True


def add_node(graph, name, values, color, fillcolor, group):
    if not graph.has_node(name):
        graph.add_node(
            name,
            style="filled",
            color=color,
            fillcolor=fillcolor,
            group=group,
        )
    for child_name in values.get("children", []):
        graph.add_edge(name, child_name)
    return graph


def remove_node(graph, node):
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
