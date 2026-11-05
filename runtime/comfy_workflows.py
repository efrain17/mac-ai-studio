"""Workflows the chat assistant creates and updates, saved where ComfyUI's Workflows panel lists
them: ComfyUI/user/default/workflows/Mac AI Studio/From chat.

Each one is two files. The panel file is the format ComfyUI's editor opens. Next to the studio,
in ~/MacAIStudio/chat-workflows, the same graph in the format ComfyUI renders (the "API format"),
with a checksum of the panel file, so a later update can tell whether it was edited by hand.
Every update keeps the previous version under chat-workflows/history.

Every graph is checked against ComfyUI's own description of its nodes (/object_info) before it
is saved: node names, input names, links and their types, choices such as model files, number
ranges, and that something saves a file. Only installed nodes can be used, so no download or
third-party node is ever involved. Standard library only.
"""
import difflib
import hashlib
import json
import pathlib
import re
import time

MARKER = "mac_ai_studio"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{1,58}[A-Za-z0-9]$")
PRIMITIVES = ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")
SEED_NAMES = ("seed", "noise_seed")


class WorkflowError(RuntimeError):
    pass


class Store:
    def __init__(self, studio_home, comfyui_dir):
        self.panel_dir = pathlib.Path(comfyui_dir) / "user" / "default" / "workflows" / "Mac AI Studio" / "From chat"
        self.data_dir = pathlib.Path(studio_home) / "chat-workflows"
        self.history_dir = self.data_dir / "history"

    def panel_file(self, name):
        return self.panel_dir / f"{name}.json"

    def data_file(self, name):
        return self.data_dir / f"{name}.json"

    def names(self):
        """Workflows the chat made that are still in the panel (one deleted there is gone)."""
        return sorted(p.stem for p in self.data_dir.glob("*.json") if self.panel_file(p.stem).exists())

    def load(self, name):
        if name not in self.names():
            raise WorkflowError(f"The chat has made no workflow named {name!r}. Its workflows: {self.names() or 'none yet'}.")
        return json.loads(self.data_file(name).read_text())

    def edited_by_hand(self, name):
        record = self.load(name)
        return sha256(self.panel_file(name).read_bytes()) != record["panel_sha256"]

    def save(self, name, api, ui, record):
        if self.data_file(name).exists():
            self.history_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for source, suffix in ((self.data_file(name), "api"), (self.panel_file(name), "panel")):
                if source.exists():
                    (self.history_dir / f"{name}-{stamp}-{suffix}.json").write_bytes(source.read_bytes())
        self.panel_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        panel = (json.dumps(ui, indent=2) + "\n").encode()
        write_atomic(self.panel_file(name), panel)
        record = {**record, "api": api, "panel_sha256": sha256(panel)}
        write_atomic(self.data_file(name), (json.dumps(record, indent=2) + "\n").encode())
        return self.panel_file(name)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def check_name(name, taken):
    name = (name or "").strip()
    if not NAME_PATTERN.match(name):
        raise WorkflowError("A workflow name has 3 to 60 letters, digits, spaces, - or _, e.g. 'Foggy harbour poster'.")
    if name.lower() in {t.lower() for t in taken}:
        raise WorkflowError(f"{name!r} is one of the studio's own workflows, which the chat does not change. Pick another name.")
    return name


# ---- Node descriptions ----------------------------------------------------------------------


def inputs_of(info):
    """(name, type, options, required) for every input of a node, in the order ComfyUI shows them."""
    sections = info.get("input", {})
    order = info.get("input_order") or {key: list(sections.get(key, {})) for key in ("required", "optional")}
    found = []
    for section in ("required", "optional"):
        for name in order.get(section, []):
            spec = sections.get(section, {}).get(name)
            if spec is None:
                continue
            kind = spec[0] if spec else "*"
            options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            found.append((name, kind, options, section == "required"))
    return found


def is_widget(kind, options):
    if isinstance(kind, list):
        return True
    if isinstance(kind, str) and kind.startswith("COMFY_DYNAMICCOMBO"):
        return True
    return kind in PRIMITIVES and not options.get("forceInput")


def choices(kind, options):
    if isinstance(kind, list):
        return kind
    if kind == "COMBO" or (isinstance(kind, str) and kind.startswith("COMFY_DYNAMICCOMBO")):
        values = options.get("options") or []
        return [v.get("key", v) if isinstance(v, dict) else v for v in values]
    return None


def default_for(kind, options):
    if "default" in options:
        return options["default"]
    values = choices(kind, options)
    if values:
        return values[0]
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(kind, None)


def describe_node(name, info, limit=30):
    parts = []
    for input_name, kind, options, required in inputs_of(info):
        values = choices(kind, options)
        if values is not None:
            shown = ", ".join(map(str, values[:limit])) + (f" … {len(values) - limit} more" if len(values) > limit else "")
            text = f"{input_name}: one of [{shown}]"
        elif is_widget(kind, options):
            bounds = " ".join(f"{k} {options[k]}" for k in ("default", "min", "max") if k in options)
            text = f"{input_name}: {kind}" + (f" ({bounds})" if bounds else "")
        else:
            text = f"{input_name}: link from a {kind} output"
        parts.append(text + ("" if required else " (optional)"))
    outputs = ", ".join(f"{i}={t}" for i, t in enumerate(info.get("output", [])))
    return (f"{name} [{info.get('category', '')}] {info.get('display_name') or name}"
            f"{' (saves files)' if info.get('output_node') else ''}\n  inputs: " + ("; ".join(parts) or "none")
            + f"\n  outputs: {outputs or 'none'}")


def search_nodes(object_info, text, limit=25):
    words = [w for w in (text or "").lower().split() if w]
    matches = []
    for name, info in object_info.items():
        haystack = " ".join(str(part or "") for part in (name, info.get("display_name"), info.get("category"),
                                                         info.get("description"))).lower()
        if all(w in haystack for w in words):
            matches.append(name)
    matches.sort(key=lambda n: (not (text or "").lower() in n.lower(), n))
    return matches[:max(1, min(int(limit or 25), 60))]


# ---- Graphs ---------------------------------------------------------------------------------


def is_link(value):
    return (isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int))
            and isinstance(value[1], int) and not isinstance(value[1], bool))


def normalize(graph):
    """Node ids as "1", "2" … in the given order, with every link renumbered to match."""
    if isinstance(graph, str):
        try:
            graph = json.loads(graph)
        except ValueError as error:
            raise WorkflowError(f"The graph is not valid JSON: {error}") from error
    if not isinstance(graph, dict) or not graph:
        raise WorkflowError('The graph is an object of nodes: {"1": {"class_type": "...", "inputs": {...}}, ...}.')
    if "nodes" in graph and "links" in graph:
        raise WorkflowError("That is the editor's format. Give the graph in API format (class_type and inputs per node).")
    mapping = {str(old): str(index) for index, old in enumerate(graph, start=1)}
    result = {}
    for old, node in graph.items():
        if not isinstance(node, dict) or "class_type" not in node:
            raise WorkflowError(f"Node {old} needs a class_type and inputs.")
        inputs = {}
        for key, value in (node.get("inputs") or {}).items():
            if is_link(value):
                source = str(value[0])
                if source not in mapping:
                    raise WorkflowError(f"Node {old} input {key!r} links to node {source}, which is not in the graph.")
                value = [mapping[source], value[1]]
            inputs[key] = value
        title = (node.get("_meta") or {}).get("title") or node.get("title") or node["class_type"]
        result[mapping[str(old)]] = {"class_type": node["class_type"], "inputs": inputs, "_meta": {"title": str(title)}}
    return result


def find_node(graph, key):
    if str(key) in graph:
        return str(key)
    wanted = str(key).strip().lower()
    hits = [i for i, n in graph.items() if n["_meta"]["title"].lower() == wanted]
    if len(hits) == 1:
        return hits[0]
    titles = ", ".join(f"{i} {n['_meta']['title']!r}" for i, n in graph.items())
    raise WorkflowError(f"No single node {key!r}. Nodes: {titles}.")


def apply_changes(graph, changes):
    """changes: {"node id or title": {"input": value}}. A value of null removes an optional input."""
    if not changes:
        return graph
    if isinstance(changes, str):
        try:
            changes = json.loads(changes)
        except ValueError as error:
            raise WorkflowError(f"changes is not valid JSON: {error}") from error
    if not isinstance(changes, dict):
        raise WorkflowError('changes looks like {"Render": {"steps": 40}, "Prompt": {"text": "..."}}.')
    graph = json.loads(json.dumps(graph))
    for key, values in changes.items():
        node_id = find_node(graph, key)
        if not isinstance(values, dict):
            raise WorkflowError(f"The change for {key!r} must be an object of inputs.")
        for name, value in values.items():
            if name == "title":
                graph[node_id]["_meta"]["title"] = str(value)
            elif value is None:
                graph[node_id]["inputs"].pop(name, None)
            else:
                if is_link(value):
                    value = [str(value[0]), value[1]]
                graph[node_id]["inputs"][name] = value
    return graph


def validate(graph, object_info):
    """Returns the graph with missing settings filled in, and notes on what was filled. Raises
    WorkflowError listing every problem found."""
    problems, notes = [], []
    graph = json.loads(json.dumps(graph))
    for node_id, node in graph.items():
        kind = node["class_type"]
        label = f"Node {node_id} ({node['_meta']['title']}, {kind})"
        info = object_info.get(kind)
        if info is None:
            close = difflib.get_close_matches(kind, list(object_info), n=3)
            problems.append(f"{label}: no such node in this ComfyUI." + (f" Did you mean {', '.join(close)}?" if close else
                                                                        " Use list_node_types to search."))
            continue
        known = {name for name, *_ in inputs_of(info)}
        for name in list(node["inputs"]):
            if name not in known and name.split(".", 1)[0] not in known:
                problems.append(f"{label}: has no input {name!r}. Its inputs: {', '.join(sorted(known)) or 'none'}.")
        for name, kind_in, options, required in inputs_of(info):
            value = node["inputs"].get(name)
            if value is None:
                if required and is_widget(kind_in, options):
                    node["inputs"][name] = default_for(kind_in, options)
                    notes.append(f"{label}: {name} set to {node['inputs'][name]!r} (its default).")
                elif required:
                    problems.append(f"{label}: needs a link into {name!r} (a {kind_in}).")
                continue
            if is_link(value):
                source = graph.get(value[0])
                source_info = object_info.get(source["class_type"]) if source else None
                if source is None:
                    problems.append(f"{label}: {name} links to node {value[0]}, which does not exist.")
                elif source_info is not None:
                    outputs = source_info.get("output", [])
                    if not 0 <= value[1] < len(outputs):
                        problems.append(f"{label}: {name} uses output {value[1]} of node {value[0]}, which has {len(outputs)}.")
                    elif not compatible(outputs[value[1]], kind_in):
                        problems.append(f"{label}: {name} needs a {kind_in}, but output {value[1]} of node {value[0]} "
                                        f"({source['class_type']}) is a {outputs[value[1]]}.")
                continue
            if not is_widget(kind_in, options):
                problems.append(f"{label}: {name} must be a link to another node's {kind_in} output, like [\"3\", 0].")
                continue
            problem = check_value(name, kind_in, options, value)
            if problem:
                problems.append(f"{label}: {problem}")
            elif kind_in == "INT":
                node["inputs"][name] = int(value)
            elif kind_in == "FLOAT":
                node["inputs"][name] = float(value)
    if not any(object_info.get(n["class_type"], {}).get("output_node") for n in graph.values()):
        problems.append("Nothing in the graph saves a file: add a SaveImage, SaveVideo or similar node.")
    cycle = find_cycle(graph)
    if cycle:
        problems.append(f"The links go in a circle: {' -> '.join(cycle)}.")
    if problems:
        raise WorkflowError("The workflow was not saved:\n- " + "\n- ".join(problems[:20])
                            + (f"\n- … {len(problems) - 20} more" if len(problems) > 20 else ""))
    return graph, notes


def compatible(output_type, input_type):
    if "*" in (output_type, input_type):
        return True
    return output_type == input_type or output_type in str(input_type).split(",")


def check_value(name, kind, options, value):
    values = choices(kind, options)
    if values is not None:
        if values and value not in values:
            close = difflib.get_close_matches(str(value), [str(v) for v in values], n=3)
            hint = f" Closest: {', '.join(close)}." if close else f" Choices: {', '.join(map(str, values[:15]))}."
            return f"{name} cannot be {value!r}.{hint}"
        if not values:
            return f"{name}: no choice is installed for it (for example no model file of that kind)."
        return None
    if kind in ("INT", "FLOAT"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{name} must be a number, not {value!r}."
        if kind == "INT" and float(value) != int(value):
            return f"{name} must be a whole number, not {value}."
        if "min" in options and value < options["min"]:
            return f"{name} is at least {options['min']}, not {value}."
        if "max" in options and value > options["max"]:
            return f"{name} is at most {options['max']}, not {value}."
    if kind == "STRING" and not isinstance(value, str):
        return f"{name} must be text."
    if kind == "BOOLEAN" and not isinstance(value, bool):
        return f"{name} must be true or false."
    return None


def find_cycle(graph):
    state = {}

    def visit(node_id, path):
        state[node_id] = "open"
        for value in graph[node_id]["inputs"].values():
            if is_link(value) and value[0] in graph:
                if state.get(value[0]) == "open":
                    return path + [node_id, value[0]]
                if value[0] not in state:
                    found = visit(value[0], path + [node_id])
                    if found:
                        return found
        state[node_id] = "done"
        return None

    for node_id in graph:
        if node_id not in state:
            found = visit(node_id, [])
            if found:
                return found
    return None


# ---- The editor's format --------------------------------------------------------------------


def widget_values(node, info):
    """The values ComfyUI's editor stores for a node's widgets, in the order it shows them."""
    values = []
    consumed = set()
    for name, kind, options, _ in inputs_of(info):
        if not is_widget(kind, options):
            continue
        value = node["inputs"].get(name)
        values.append(default_for(kind, options) if value is None or is_link(value) else value)
        consumed.add(name)
        # The editor adds a "control after generate" choice after seeds. The studio's own workflows
        # randomize the render seed (ComfyUI marks it) and keep other seeds, such as the reveal
        # pattern's, fixed.
        if kind == "INT" and options.get("control_after_generate"):
            values.append("randomize")
        elif kind == "INT" and name in SEED_NAMES:
            values.append("fixed")
        if options.get("image_upload") or options.get("video_upload") or options.get("audio_upload"):
            values.append("image" if options.get("image_upload") else "video" if options.get("video_upload") else "audio")
        # Inputs that belong to a dynamic choice, such as "format.codec" after "format".
        for key, sub_value in node["inputs"].items():
            if key.startswith(name + ".") and not is_link(sub_value):
                values.append(sub_value)
                consumed.add(key)
    return values


def to_editor(graph, object_info, note=None, marker=None):
    nodes, links = {}, []
    for node_id, node in graph.items():
        info = object_info[node["class_type"]]
        slots = []
        for name, kind, options, _ in inputs_of(info):
            value = node["inputs"].get(name)
            if not is_widget(kind, options):
                slots.append({"name": name, "type": kind, "link": None})
            elif is_link(value):
                slots.append({"name": name, "type": kind if isinstance(kind, str) else "COMBO",
                              "widget": {"name": name}, "link": None})
        widgets = widget_values(node, info)
        title = node["_meta"]["title"]
        entry = {
            "id": int(node_id), "type": node["class_type"], "pos": [0, 0],
            "size": [340, 70 + 26 * len(widgets) + 22 * len(slots)], "flags": {}, "order": 0, "mode": 0,
            "inputs": slots,
            "outputs": [{"name": (info.get("output_name") or info.get("output"))[i], "type": t, "slot_index": i, "links": []}
                        for i, t in enumerate(info.get("output", []))],
            "properties": {"Node name for S&R": node["class_type"]},
            "widgets_values": widgets,
        }
        if title and title != (info.get("display_name") or node["class_type"]):
            entry["title"] = title
        nodes[node_id] = entry
    for node_id, node in graph.items():
        entry = nodes[node_id]
        for slot_index, slot in enumerate(entry["inputs"]):
            value = node["inputs"].get(slot["name"])
            if not is_link(value):
                continue
            link_id = len(links) + 1
            source_id, source_slot = value
            links.append([link_id, int(source_id), source_slot, int(node_id), slot_index, slot["type"]])
            slot["link"] = link_id
            nodes[source_id]["outputs"][source_slot]["links"].append(link_id)
    place(graph, nodes)
    last_id = max(int(i) for i in graph)
    if note:
        last_id += 1
        nodes["note"] = {
            "id": last_id, "type": "Note", "title": "Read me", "pos": [60, -260], "size": [620, 200],
            "flags": {}, "order": len(nodes), "mode": 0, "inputs": [], "outputs": [],
            "properties": {"text": ""}, "widgets_values": [note], "color": "#432", "bgcolor": "#653",
        }
    return {
        "last_node_id": last_id, "last_link_id": len(links), "nodes": list(nodes.values()), "links": links,
        "groups": [], "config": {}, "extra": {"ds": {"scale": 0.75, "offset": [0, 0]}, MARKER: marker or {}},
        "version": 0.4,
    }


def place(graph, nodes):
    """Left to right by how many steps each node is from the start; also sets the run order."""
    depth = {}

    def depth_of(node_id):
        if node_id not in depth:
            parents = [v[0] for v in graph[node_id]["inputs"].values() if is_link(v) and v[0] in graph]
            depth[node_id] = 1 + max((depth_of(p) for p in parents), default=-1)
        return depth[node_id]

    used = {}
    for order, node_id in enumerate(sorted(graph, key=lambda i: (depth_of(i), int(i)))):
        column = depth_of(node_id)
        nodes[node_id]["pos"] = [60 + column * 400, used.get(column, 60)]
        nodes[node_id]["order"] = order
        used[column] = used.get(column, 60) + nodes[node_id]["size"][1] + 60
