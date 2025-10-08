from lxml import etree
from collections import namedtuple, defaultdict
import operator
import time
import random
import numpy as np
import argparse
import tempfile
import shutil
import os

args_parser = argparse.ArgumentParser(description="Generate 3D Switch Blocks (SBs) for a given VPR RR Graph without 3D SBs")

args_parser.add_argument("-f", "--input_file",type=str, help="The file path to the VPR RR Graph XML file", required=True)

args_parser.add_argument("-o", "--output_path", type=str, help="The file path to the output VPR RR Graph XML file", required=True)

args_parser.add_argument("-p", "--percent_connectivity", type=float, help="The percentage of SBs on fabric that are 3D. Must be a float between 0 and 1", required=True)

args_parser.add_argument("-c", "--connection_type", choices=["subset", "wilton", "wilton_2", "wilton_3", "custom"], help="The connection pattern to use for the 3D SBs. Options are: subset, wilton, wilton_2, wilton_3, custom [--sb_input_pattern and --sb_output_pattern are required for this option]", required=True)

args_parser.add_argument("-vp", "--vertical_connectivity_percentage", type=float, help="The percentage of channels at each SB that are connected vertically. Must be a float between 0 and 1", default=1.0)

args_parser.add_argument("-v", "--verbose", help="Whether to print verbose output.", action="store_true")

args_parser.add_argument("-a", "--arch_file", type=str, help="The file path to the VPR architecture XML file", required=True)

args_parser.add_argument("--sb_3d_segment", type=str, help="The name of the 3D segment to use for the 3D SBs (Needs to be defined in the architecture XML file, by default is `3D_SB_connection`)", default="3D_SB_connection")

args_parser.add_argument("--sb_3d_switch", type=str, help="The name of the 3D switch to use for the 3D SBs (Needs to be defined in the architecture XML file, by default is `3D_SB_switch`)", default="3D_SB_switch")

args_parser.add_argument("--sb_location_pattern", choices=["repeated_interval", "random", "custom", "core", "perimeter", "rows", "columns"], help="The pattern to use for the location of the 3D SBs. Options are: repeated_interval, random, custom. If custom then the option `--sb_grid_csv` option must be specified", default="repeated_interval")

args_parser.add_argument("--sb_grid_csv", type=str, help="The file path to the CSV file containing the custom SB locations. The CSV file should have two columns: x and y. The x and y coordinates of the SBs will be read from this file. This option is only used if the `--sb_location_pattern` option is set to `custom`. Run `sb_grid_generator.py` script with `python3 sb_grid_generator.py --width <fabric width> --height <fabric height> --file_path <optional: path_to_write_csv>`, to generate a blank csv template for the grid locations.", default="")

#TODO: Make it actually be any number of crossings, currently either 1 or max
args_parser.add_argument("--max_number_of_crossings", type=int, help="The maximum number of crossings to allow in a single connection in a 3D SB. -1 means there is no maximum, every signal can cross at every possible location, currently any other value is the same result as 1 (to be implemented)", default=-1)

args_parser.add_argument("--sb_input_pattern", nargs=4, type=int, metavar=('XYChanX', 'XYChanY', 'X+1YChanX', 'XY+1ChanY'), help="The pattern to use for the input connections of the 3D SBs. The pattern is a list of 4 integers. See documentation or `create_custom_connection_3d_sb` function for more details. This option is required and only used if the `--connection_type` option is set to `custom`.", default=None)

args_parser.add_argument("--sb_output_pattern", nargs=4, metavar=('XYChanX', 'XYChanY', 'X+1YChanX', 'XY+1ChanY'), type=int, help="The pattern to use for the output connections of the 3D SBs. The pattern is a list of 4 integers. See documentation or `create_custom_connection_3d_sb` function for more details. This option is required and only used if the `--connection_type` option is set to `custom`.", default=None)

args = args_parser.parse_args()


node_struct = namedtuple("Node", ["id", "type", "layer", "xhigh", "xlow", "yhigh", "ylow", "side", "direction", "ptc", "segment"])
edge_struct = namedtuple("Edge", ["src_node", "sink_node", "src_layer", "sink_layer", "switch"])

node_data = {}

max_node_id = 0

# Create an index for quick lookups
node_index = defaultdict(list)

ptc_counter = defaultdict(int)

device_max_x = 0
device_max_y = 0
device_max_layer = 0

# Segment ID to use for 3D SB connection
segment_id = 0

# Switch ID to use for 3D SB connection
switch_id = 2

# Dictionary to hold the segment name and it's connection pattern key: segment name, value: connection pattern (list of bools)
pattern_dict = defaultdict(list)

def print_verbose(*args, **kwargs):
    global verbose
    if verbose:
        print(*args, **kwargs)

def add_node(node):
    node_data[node.id] = node
    if node.direction != "NONE":
        x_low = int(node.xlow)
        y_low = int(node.ylow)
        x_high = int(node.xhigh)
        y_high = int(node.yhigh)

        if x_high == x_low and y_high == y_low:
            key = (node.type, int(node.xlow), int(node.ylow), int(node.layer))
            node_index[key].append(node)
            return

        if x_high != x_low:
            x_range = x_high - x_low
            for x in range (x_low, x_high + 1):
                key = (node.type, x, y_low, int(node.layer))
                node_index[key].append(node)
            return
        
        y_range = y_high - y_low
        for y in range (y_low, y_high + 1):
            key = (node.type, x_low, y, int(node.layer))
            node_index[key].append(node)
        return

def remove_node(node_id):
    node = node_data.pop(node_id, None)
    if node and node.direction != "NONE":
        key = (node.type, int(node.xlow), int(node.ylow), int(node.layer))
        if node in node_index[key]:
            node_index[key].remove(node)
            if not node_index[key]:
                del node_index[key]

def update_node(node):
    # Remove the old node entry if it exists
    old_node = node_data.get(node.id)
    if old_node:
        if old_node.direction != "NONE":
            old_key = (old_node.type, int(old_node.xlow), int(old_node.ylow), int(old_node.layer))
            if old_node in node_index[old_key]:
                node_index[old_key].remove(old_node)
                if not node_index[old_key]:
                    del node_index[old_key]
    
    # Add the updated node
    node_data[node.id] = node
    if node.direction != "NONE":
        new_key = (node.type, int(node.xlow), int(node.ylow), int(node.layer))
        node_index[new_key].append(node)

def read_structure_streaming(file_path):
    """
    Streaming version of read_structure that doesn't load entire XML into memory
    """
    start_time = time.time()
    print_verbose(f"Starting streaming read of {file_path}")
    
    # Create streaming parser
    parser = etree.iterparse(
        file_path,
        events=('start', 'end'),
        huge_tree=True,
        remove_blank_text=True,
        remove_comments=True
    )
    
    # Process the file
    extract_nodes_streaming(parser)
    

    global ptc_counter
    # Start PTC values for 3D Channels at 1000 to avoid overlap with any horizontal channels. 
    # IMPORTANT CONSIDERATION: If your channel width is greater than 1000, then you should adjust the starting ptc value to be higher (change 1000 to a larger number that's  channel width)
    for layer in range(device_max_layer + 1):
        for x in range(device_max_x + 1):
            for y in range(device_max_y + 1):
                key = (layer, x, y)
                ptc_counter[key] = 1000

    end_time = time.time()
    print_verbose(f"Reading XML file took {((end_time - start_time) * 1000):0.2f} ms")

def extract_nodes_streaming(parser):
    """
    Streaming version of extract_nodes that processes one node at a time
    """
    print_verbose(f"Extracting Nodes")
    start_time = time.time()
    
    global max_node_id, device_max_layer, device_max_x, device_max_y, ptc_counter
    
    in_rr_nodes = False
    nodes_processed = 0
    
    for event, elem in parser:
        # Check if we're entering rr_nodes section
        if event == 'start' and elem.tag == 'rr_nodes':
            in_rr_nodes = True
            continue
        
        # Check if we're leaving rr_nodes section
        if event == 'end' and elem.tag == 'rr_nodes':
            in_rr_nodes = False
            # Clear the rr_nodes element to free memory
            elem.clear()
            break
        
        # Process node elements within rr_nodes
        if event == 'end' and elem.tag == 'node' and in_rr_nodes:
            node_id = elem.get("id")
            
            if node_id:
                # Update max_node_id
                max_node_id = max(max_node_id, int(node_id))
                
                nodes_processed += 1
                if nodes_processed % 100000 == 0:
                    print_verbose(f"\tProcessed {nodes_processed} nodes")
                
                type_attr = elem.get("type")
                
                # Only process CHANX and CHANY nodes
                if type_attr in ["CHANX", "CHANY"]:
                    # Extract location data
                    loc = elem.find("loc")
                    if loc is not None:
                        layer = loc.get("layer")
                        xhigh = loc.get("xhigh")
                        xlow = loc.get("xlow")
                        yhigh = loc.get("yhigh")
                        ylow = loc.get("ylow")
                        side = loc.get("side")
                        ptc_node = loc.get("ptc")
                        
                        # Update ptc_counter
                        # key = (int(layer), int(xlow), int(ylow))
                        # ptc_counter[key] = max(1000, int(ptc_node))
                        
                        # Update device dimensions
                        device_max_layer = max(device_max_layer, int(layer))
                        if type_attr == "CHANX":
                            device_max_x = max(device_max_x, int(xhigh))
                        elif type_attr == "CHANY":
                            device_max_y = max(device_max_y, int(yhigh))
                        
                        # Get direction
                        direction = elem.get("direction", "")
                        
                        # Get segment info
                        segment = elem.find("segment")
                        id_segment = 0
                        if segment is not None:
                            id_segment = int(segment.get("segment_id", 0))
                        
                        # Create and add node
                        node = node_struct(
                            node_id, type_attr, layer, xhigh, xlow, 
                            yhigh, ylow, side, direction, ptc_node, id_segment
                        )
                        add_node(node)
            
            # IMPORTANT: Clear the element to free memory
            elem.clear()
            # Also remove preceding siblings that are already processed
            parent = elem.getparent()
            if parent is not None:
                # Remove all previous siblings to free memory
                while elem.getprevious() is not None:
                    del parent[0]
    
    end_time = time.time()
    print_verbose(f"max_node_id: {max_node_id}")
    print_verbose(f"Total nodes processed: {nodes_processed}")
    print_verbose(f"Extracting all nodes took {((end_time - start_time) * 1000):0.2f} ms")

def write_nodes_batch(outfile, nodes_to_write):
    """
    Write nodes in batches without creating etree elements
    """
    global segment_id
    
    BATCH_SIZE = 10000
    nodes_written = 0
    
    for i in range(0, len(nodes_to_write), BATCH_SIZE):
        batch = nodes_to_write[i:i + BATCH_SIZE]
        
        for node in batch:
            # Write node directly as formatted string
            outfile.write(f'  <node capacity="1" direction="{node.direction}" id="{node.id}" type="{node.type}">\n')
            if node.type.endswith("/"):
                print(f"ERROR: Node type {node.type} should not end with a slash")
            outfile.write(f'    <loc layer="{node.layer}" ptc="{node.ptc}" xhigh="{node.xhigh}" xlow="{node.xlow}" yhigh="{node.yhigh}" ylow="{node.ylow}"/>\n')
            outfile.write(f'    <timing C="0" R="0"/>\n')
            outfile.write(f'    <segment segment_id="{segment_id}"/>\n')
            outfile.write(f'  </node>\n')
            
        nodes_written += len(batch)
        if nodes_written % 100000 == 0:
            print_verbose(f"\tWritten {nodes_written}/{len(nodes_to_write)} nodes")
    
    print_verbose(f"Finished writing {nodes_written} new nodes")

def write_edges_batch(outfile, edges_to_write):
    """
    Write edges in batches
    """
    global switch_id
    
    BATCH_SIZE = 10000
    edges_written = 0
    
    for i in range(0, len(edges_to_write), BATCH_SIZE):
        batch = edges_to_write[i:i + BATCH_SIZE]
        
        for edge in batch:
            outfile.write(f'  <edge sink_node="{edge.sink_node}" src_node="{edge.src_node}" switch_id="{edge.switch}"/>\n')
            
        edges_written += len(batch)
        if edges_written % 100000 == 0:
            print_verbose(f"\tWritten {edges_written}/{len(edges_to_write)} edges")
    
    print_verbose(f"Finished writing {edges_written} new edges")

def write_sb_nodes_and_edges_streaming_simple(input_file_path, output_file_path, nodes_to_write, edges_to_write):
    """
    Simple line-based streaming that preserves original formatting exactly
    """
    start_time = time.time()
    print_verbose(f"Starting streaming write: {len(nodes_to_write)} nodes, {len(edges_to_write)} edges")
    
    temp_fd, temp_path = tempfile.mkstemp(suffix='.xml', dir=os.path.dirname(output_file_path))
    
    try:
        with open(input_file_path, 'r', encoding='utf-8') as infile, \
             os.fdopen(temp_fd, 'w', encoding='utf-8') as outfile:
            
            nodes_written = False
            edges_written = False
            
            # Process line by line to preserve exact formatting
            for line in infile:
                # Insert new nodes before </rr_nodes>
                if '</rr_nodes>' in line and not nodes_written and nodes_to_write:
                    write_nodes_batch(outfile, nodes_to_write)
                    nodes_written = True
                
                # Insert new edges before </rr_edges>
                elif '</rr_edges>' in line and not edges_written and edges_to_write:
                    write_edges_batch(outfile, edges_to_write)
                    edges_written = True
                
                # Write the original line exactly as it was
                outfile.write(line)
        
        shutil.move(temp_path, output_file_path)
        end_time = time.time()
        print_verbose(f"Streaming write completed in {((end_time - start_time) * 1000):0.2f} ms")
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e

def read_structure(file_path, parser):
    start_time = time.time()
    try:
        tree = etree.parse(file_path, parser=parser)
        root = tree.getroot()
        end_time = time.time()
        print_verbose(f"Reading XML file took { ((end_time - start_time) * 1000):0.2f} ms")
        return root, tree

    except Exception as e:
        print_verbose(f"Error reading XML file: {e}")
        return None

def extract_nodes(root):
    print_verbose(f"Extracting Nodes")
    start_time = time.time()
    rr_nodes = root.find("rr_nodes")
    
    for node in rr_nodes.findall("node"):
        node_id = node.get("id")

        global max_node_id
        max_node_id = max(max_node_id, int(node_id))

        if int(node_id) % 100000 == 0:
            print_verbose(f"\tProcessed {node_id} nodes")

        type = node.get("type")

        if type != "CHANX" and type != "CHANY":
            continue
        
        loc = node.find("loc")

        layer = loc.get("layer")
        xhigh = loc.get("xhigh")
        xlow = loc.get("xlow")
        yhigh = loc.get("yhigh")
        ylow = loc.get("ylow")
        side = loc.get("side")
        ptc_node = loc.get("ptc")

        # global ptc_counter
        # key = (int(layer), int(xlow), int(ylow))
        # ptc_counter[key] = max(1000, int(ptc_node))

        direction = node.get("direction")

        global device_max_layer, device_max_x, device_max_y
        device_max_layer = max(device_max_layer, int(layer))
        if type == "CHANX":
            device_max_x = max(device_max_x, int(xhigh))
        elif type == "CHANY":
            device_max_y = max(device_max_y, int(xhigh))

        segment = node.find("segment")
        id_segment = int(segment.get("segment_id"))

        # if segment_id == "0":

        add_node(node_struct(node_id, type, layer, xhigh, xlow, yhigh, ylow, side, direction, ptc_node, id_segment))

    global ptc_counter
    # Start PTC values for 3D Channels at 1000 to avoid overlap with any horizontal channels. 
    # IMPORTANT CONSIDERATION: If your channel width is greater than 1000, then you should adjust the starting ptc value to be higher (change 1000 to a larger number that's  channel width)
    for layer in range(device_max_layer + 1):
        for x in range(device_max_x + 1):
            for y in range(device_max_y + 1):
                key = (layer, x, y)
                ptc_counter[key] = 1000

    end_time = time.time()
    print_verbose(f"max_node_id: {max_node_id}")
    print_verbose(f"Extracting all nodes took { ((end_time - start_time) * 1000):0.2f} ms")

def create_node(node_id, type, layer, xhigh, xlow, yhigh, ylow, side, direction, ptc_node=0, segment="0"):
    new_node = node_struct(node_id, type, layer, xhigh, xlow, yhigh, ylow, side, direction, ptc_node, segment)
    add_node(new_node)
    return new_node

def node_string(node: node_struct):
    ret = f"""<node capacity=\"1\" type=\"{node.type}\" id=\"{node.id}\" type=\"{node.type}\"><loc layer=\"{node.layer}\" ptc=\"0\" xhigh=\"{node.xhigh}\" xlow=\"{node.xlow}\" yhigh=\"{node.yhigh}\" ylow=\"{node.ylow}\"/>\n<timing C="0" R="0"/>\n<segment segment_id="0"/>\n</node>"""
    return ret

NODE_TEMPLATE = '<node capacity="1" direction="{direction}" id="{id}" type="{type}"/>'
LOC_TEMPLATE = '<loc layer="{layer}" ptc="{ptc}" xhigh="{xhigh}" xlow="{xlow}" yhigh="{yhigh}" ylow="{ylow}"/>'
TIMING_ELEMENT = etree.Element("timing", C="0", R="0")
SEGMENT_ELEMENT = etree.Element("segment", segment_id="0")

def node_xml_element(node):
    global segment_id
    # key = (node.layer, node.xlow, node.ylow)
    # ptc[key] += 1

    # Create node using string template
    node_str = f'<node capacity="1" direction="{node.direction}" id="{node.id}" type="{node.type}"/>'
    new_node = etree.fromstring(node_str)

    # Create loc using string template
    loc_str = f'<loc layer="{node.layer}" ptc="{node.ptc}" xhigh="{node.xhigh}" xlow="{node.xlow}" yhigh="{node.yhigh}" ylow="{node.ylow}"/>'
    new_node.append(etree.fromstring(loc_str))

    timing = etree.Element("timing", C="0", R="0")
    segment = etree.Element("segment", segment_id=str(segment_id))

    # Add pre-created elements
    new_node.append(timing)
    new_node.append(segment)

    return new_node

def edge_string(edge: edge_struct):
    return f"""<edge sink_node=\"{edge.sink_node}\" src_node=\"{edge.sink_node}\" switch_id=\"0\"></edge>\n"""

EDGE_TEMPLATE = '<edge sink_node="{sink}" src_node="{src}" switch_id="{switch}"/>'

def edge_xml_element(edge):
    return etree.fromstring(
        EDGE_TEMPLATE.format(
            sink=edge.sink_node,
            src=edge.src_node,
            switch=edge.switch
        )
    )

# temporary fix for mapping segment id at output to its correct switch
node_switch_id = {
    "0": "2",
    "1": "3",
    "2": "7"
}

segment_to_mux_str = {}
segment_to_mux_id = {}
segment_str_to_id = {}
switch_str_to_id = {}

def create_edge(src_node, sink_node, src_layer, sink_layer, output_segment):
    # need to figure put edge switch based on sink_node segment id
    global switch_id
    switch=segment_to_mux_id.get(str(output_segment), str(switch_id))

    new_edge = edge_struct(src_node, sink_node, src_layer, sink_layer, switch)
    # add_edge((src_node, sink_node), new_edge)
    return new_edge

def does_node_connect_to_sb(node, x, y):
    global pattern_dict
    node_segment = node.segment

    if node_segment not in pattern_dict:
        print(f"ERROR: Segment {node_segment} does not have a connection pattern")
        exit(1)
    
    pattern = pattern_dict[node_segment]

    if node.type == "CHANX":
        pattern_index = x - int(node.xlow) + 1
        if pattern_index < 0 or pattern_index >= len(pattern):
            print(f"ERROR: Pattern index {pattern_index} out of bounds for node {node} with pattern {pattern}")
            exit(1)
        return pattern[pattern_index]
    
    else:
        pattern_index = y - int(node.ylow) + 1
        if pattern_index < 0 or pattern_index >= len(pattern):
            print(f"ERROR: Pattern index {pattern_index} out of bounds for node {node} with pattern {pattern}")
            exit(1)
        return pattern[pattern_index]

def find_chan_nodes(x, y, layer_num_1, layer_num_2):
    '''
        Function to find the channel nodes at a given location
        
        Returns the channels nodes at locations (x, y) and (x+1, y) and (x, y+1) and (x+1, y+1) on layers layer_num_1 and layer_num_2
    '''
    chan_nodes = []
    keys = [
        ("CHANX", x, y, layer_num_2),
        ("CHANY", x, y, layer_num_2),
        ("CHANX", x + 1, y, layer_num_2),
        ("CHANY", x, y + 1, layer_num_2),
        ("CHANX", x, y, layer_num_1),
        ("CHANY", x, y, layer_num_1),
        ("CHANX", x + 1, y, layer_num_1),
        ("CHANY", x, y + 1, layer_num_1)
    ]
    
    for key in keys:
        chan_nodes.extend(node_index.get(key, []))
    
    # remove duplicates
    chan_nodes = list(set(chan_nodes))
    chan_nodes = [node for node in chan_nodes if does_node_connect_to_sb(node, x, y)]

    return chan_nodes

def sort_chan_nodes_into_input_and_output(chan_nodes, x, y, layer_num):

    layer_1_sb_input_nodes = []
    layer_1_sb_output_nodes = []
    layer_0_sb_input_nodes = []
    layer_0_sb_output_nodes = []


    for node in chan_nodes:
        if node.layer == str(layer_num):
            if node.direction == "INC_DIR":
                if (int(node.xlow) == int(x) + 1 and int(node.ylow) == int(y)) or (int(node.xlow) == int(x) and int(node.ylow) == int(y) + 1):
                    layer_1_sb_output_nodes.append(node)

                elif int(node.xhigh) >= int(x) and int(node.yhigh) >=  int(y):
                    layer_1_sb_input_nodes.append(node)

                else:
                    print_verbose(f"ERROR: {node} can't be classified as input or output at location X: {x} Y: {y}")
                    exit(1)

            elif node.direction == "DEC_DIR":
                if int(node.xhigh) == int(x) and int(node.yhigh) == int(y):
                    layer_1_sb_output_nodes.append(node)

                elif (int(node.xlow) <= int(x) + 1 and int(node.ylow) == int(y)) or (int(node.xlow) == int(x) and int(node.ylow) <= int(y) + 1):
                    layer_1_sb_input_nodes.append(node)

                else:
                    print_verbose(f"ERROR: {node} can't be classified as input or output at location X: {x} Y: {y}")
                    exit(1)
            
            else:
                print_verbose(f"ERROR: {node} can't be classified as input or output at location X: {x} Y: {y}")
                exit(1)
            
            
        else:

            if node.direction == "INC_DIR":
                if (int(node.xlow) == int(x) + 1 and int(node.ylow) == int(y)) or (int(node.xlow) == int(x) and int(node.ylow) == int(y) + 1):
                    layer_0_sb_output_nodes.append(node)

                elif int(node.xhigh) >= int(x) and int(node.yhigh) >=  int(y):
                    layer_0_sb_input_nodes.append(node)

                else:
                    print_verbose(f"ERROR: {node} can't be classified as input or output at location X: {x} Y: {y}")
                    exit(1)

            elif node.direction == "DEC_DIR":
                if int(node.xhigh) == int(x) and int(node.yhigh) == int(y):
                    layer_0_sb_output_nodes.append(node)

                elif (int(node.xlow) <= int(x) + 1 and int(node.ylow) == int(y)) or (int(node.xlow) == int(x) and int(node.ylow) <= int(y) + 1):
                    layer_0_sb_input_nodes.append(node)

                else:
                    print_verbose(f"ERROR: {node} can't be classified as input or output at location X: {x} Y: {y}")
                    exit(1)
           
            else:
                print_verbose(f"ERROR: {node} can't be classified as input or output at location X: {x} Y: {y}")
                exit(1)

            

    # A bit dumb to look at but this is just to remove any duplicates since if there's long wires they can appear at multiple different locations
    return list(set(layer_0_sb_input_nodes)), list(set(layer_0_sb_output_nodes)), list(set(layer_1_sb_input_nodes)), list(set(layer_1_sb_output_nodes))

def connect_sb_nodes_combined(input_nodes, output_nodes, x, y, input_layer, output_layer):
    global max_node_id
    global segment_id

    new_edges = [None] * (len(input_nodes) + len(output_nodes) + 1)
    edge_idx = 0

    key = (int(input_layer), int(x), int(y))
    ptc_val = ptc_counter[key]
    ptc_val += 1
    input_layer_none_nodes =[create_node(max_node_id + 1, "CHANX", input_layer, x, x, y, y, "", "NONE", ptc_val, segment_id)]
    ptc_counter[key] = ptc_val

    key = (int(output_layer), int(x), int(y))
    ptc_val = ptc_counter[key]
    ptc_val += 1
    output_layer_none_nodes = [create_node(max_node_id + 2, "CHANX", output_layer, x, x, y, y, "", "NONE", ptc_val, segment_id)]
    ptc_counter[key] = ptc_val
    
    max_node_id += 2

    # connect the input nodes to the none node
    for input_node in input_nodes:
        new_edges[edge_idx] = create_edge(input_node.id, input_layer_none_nodes[0].id, input_node.layer, input_layer_none_nodes[0].layer, input_layer_none_nodes[0].segment)
        edge_idx += 1
    
    # connect the none node to the output nodes
    for output_node in output_nodes:
        new_edges[edge_idx] = create_edge(output_layer_none_nodes[0].id, output_node.id, output_layer_none_nodes[0].layer, output_node.layer, output_node.segment)
        edge_idx += 1

    # connect the two none nodes
    new_edges[edge_idx] = create_edge(input_layer_none_nodes[0].id, output_layer_none_nodes[0].id, input_layer_none_nodes[0].layer, output_layer_none_nodes[0].layer, output_layer_none_nodes[0].segment)

    return input_layer_none_nodes, output_layer_none_nodes, new_edges

def write_sb_nodes(structure, nodes_to_write):
    rr_nodes = structure.find("rr_nodes")
    for node in nodes_to_write:
        new_node = node_xml_element(node)
        rr_nodes.append(new_node)

# @profile    
def write_sb_edges(structure, edges_to_write):
    global switch_id
    rr_edges = structure.find("rr_edges")
    for edge in edges_to_write:
        new_edge = edge_xml_element(edge)
        rr_edges.append(new_edge)

def sort_nodes(nodes):
    #sort nodes by id in increasing order
    return sorted(nodes, key=operator.attrgetter("id"))

def sort_chan_nodes_by_direction(chan_nodes, x, y):
    '''
        Function to sort the chan nodes into the correct lists based on the location of the node
    '''
    x_y_chanx_chan_nodes = [None] * len(chan_nodes)
    x_y_chany_chan_nodes = [None] * len(chan_nodes)
    x_plus_1_y_chanx_chan_nodes = [None] * len(chan_nodes)
    x_y_plus_1_chany_chan_nodes = [None] * len(chan_nodes)
    
    x_y_chanx_chan_nodes_idx = 0
    x_y_chany_chan_nodes_idx = 0
    x_plus_1_y_chanx_chan_nodes_idx = 0
    x_y_plus_1_chany_chan_nodes_idx = 0

    for input_node in chan_nodes:

        node_type = input_node.type
        node_dir = input_node.direction
        
        if node_type == "CHANX":

            # The only time a INC CHANX node is at location x plus 1 is when it's being driven, 
            if node_dir == "INC_DIR":
                if (int(input_node.xlow) == int(x) + 1 and int(input_node.ylow) == int(y)) or (int(input_node.xlow) == int(x) and int(input_node.ylow) == int(y) + 1):
                    x_plus_1_y_chanx_chan_nodes[x_plus_1_y_chanx_chan_nodes_idx] = input_node
                    x_plus_1_y_chanx_chan_nodes_idx += 1
                else:
                    x_y_chanx_chan_nodes[x_y_chanx_chan_nodes_idx] = input_node
                    x_y_chanx_chan_nodes_idx += 1
            
            # The only time a DEC CHANX node is at location x is when it's being driven
            elif node_dir == "DEC_DIR":
                if int(input_node.xhigh) == int(x) and int(input_node.yhigh) == int(y):
                    x_y_chanx_chan_nodes[x_y_chanx_chan_nodes_idx] = input_node
                    x_y_chanx_chan_nodes_idx += 1
                else:
                    x_plus_1_y_chanx_chan_nodes[x_plus_1_y_chanx_chan_nodes_idx] = input_node
                    x_plus_1_y_chanx_chan_nodes_idx += 1

            else: 
                print_verbose(f"ERROR: Input node is not in the correct location, node: {input_node}")

        elif node_type == "CHANY":

            # The only time a INC CHANY node is at location y plus 1 is when it's being driven,
            if node_dir == "INC_DIR":
                if (int(input_node.xlow) == int(x) + 1 and int(input_node.ylow) == int(y)) or (int(input_node.xlow) == int(x) and int(input_node.ylow) == int(y) + 1):
                    x_y_plus_1_chany_chan_nodes[x_y_plus_1_chany_chan_nodes_idx] = input_node
                    x_y_plus_1_chany_chan_nodes_idx += 1
                else:
                    x_y_chany_chan_nodes[x_y_chany_chan_nodes_idx] = input_node
                    x_y_chany_chan_nodes_idx += 1

            # The only time a DEC CHANY node is at location y is when it's being driven
            elif node_dir == "DEC_DIR":
                if int(input_node.xhigh) == int(x) and int(input_node.yhigh) == int(y):
                    x_y_chany_chan_nodes[x_y_chany_chan_nodes_idx] = input_node
                    x_y_chany_chan_nodes_idx += 1
                else:
                    x_y_plus_1_chany_chan_nodes[x_y_plus_1_chany_chan_nodes_idx] = input_node
                    x_y_plus_1_chany_chan_nodes_idx += 1

            else: 
                print_verbose(f"ERROR: Input node is not in the correct location, node: {input_node}")
        else:
            print_verbose(f"ERROR: Input node is not in the correct location, node: {input_node}")
        
    #sort the nodes by ptc
    x_y_chanx_chan_nodes = sorted(x_y_chanx_chan_nodes[:x_y_chanx_chan_nodes_idx], key=lambda x: int(x.ptc))
    x_y_chany_chan_nodes = sorted(x_y_chany_chan_nodes[:x_y_chany_chan_nodes_idx], key=lambda x: int(x.ptc))
    x_plus_1_y_chanx_chan_nodes = sorted(x_plus_1_y_chanx_chan_nodes[:x_plus_1_y_chanx_chan_nodes_idx], key=lambda x: int(x.ptc))
    x_y_plus_1_chany_chan_nodes = sorted(x_y_plus_1_chany_chan_nodes[:x_y_plus_1_chany_chan_nodes_idx], key=lambda x: int(x.ptc))

    return x_y_chanx_chan_nodes, x_y_chany_chan_nodes, x_plus_1_y_chanx_chan_nodes, x_y_plus_1_chany_chan_nodes

def create_subset_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=-1):
    input_layer_none_nodes = []
    output_layer_none_nodes = []
    new_edges = []

    # If there are no outputs then there is no wya to create a 3D SB at a given location
    if len(x_y_chanx_output_nodes) == 0 and len(x_y_chany_output_nodes) == 0 and len(x_plus_1_y_chanx_output_nodes) == 0 and len(x_y_plus_1_chany_output_nodes) == 0:
        return input_layer_none_nodes, output_layer_none_nodes, new_edges

    x_y_chanx_input_nodes_len = len(x_y_chanx_input_nodes)
    x_y_chany_input_nodes_len = len(x_y_chany_input_nodes)
    x_plus_1_y_chanx_input_nodes_len = len(x_plus_1_y_chanx_input_nodes)
    x_y_plus_1_chany_input_nodes_len = len(x_y_plus_1_chany_input_nodes)

    x_y_chanx_output_nodes_len = len(x_y_chanx_output_nodes)
    x_y_chany_output_nodes_len = len(x_y_chany_output_nodes)
    x_plus_1_y_chanx_output_nodes_len = len(x_plus_1_y_chanx_output_nodes)
    x_y_plus_1_chany_output_nodes_len = len(x_y_plus_1_chany_output_nodes)

    for i in range(max_output_len):

        input_nodes_to_send = []
        output_nodes_to_send = []

        if 0 < x_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chanx_input_nodes[j % x_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chanx_input_nodes[i % x_y_chanx_input_nodes_len])
        if 0 < x_y_chany_input_nodes_len:
            if max_crossings == -1 and x_y_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chany_input_nodes[j % x_y_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chany_input_nodes[i % x_y_chany_input_nodes_len])
        if 0 < x_plus_1_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_plus_1_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_plus_1_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[j % x_plus_1_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[i % x_plus_1_y_chanx_input_nodes_len])
        if 0 < x_y_plus_1_chany_input_nodes_len:
            if max_crossings == -1 and x_y_plus_1_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_plus_1_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[j % x_y_plus_1_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[i % x_y_plus_1_chany_input_nodes_len])

        if 0 < x_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_y_chanx_output_nodes[i % x_y_chanx_output_nodes_len])
        if 0 < x_y_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_chany_output_nodes[i % x_y_chany_output_nodes_len])
        if 0 < x_plus_1_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_plus_1_y_chanx_output_nodes[i % x_plus_1_y_chanx_output_nodes_len])
        if 0 < x_y_plus_1_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_plus_1_chany_output_nodes[i % x_y_plus_1_chany_output_nodes_len])

        input_layer_none_nodes_temp, output_layer_none_nodes_temp, new_edges_temp = connect_sb_nodes_combined(input_nodes_to_send, output_nodes_to_send, x, y, input_layer, output_layer)
        input_layer_none_nodes.extend(input_layer_none_nodes_temp)
        output_layer_none_nodes.extend(output_layer_none_nodes_temp)
        new_edges.extend(new_edges_temp)
    
    return input_layer_none_nodes, output_layer_none_nodes, new_edges

def create_wilton_3_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=-1):
    input_layer_none_nodes = []
    output_layer_none_nodes = []
    new_edges = []

    # If there are no outputs then there is no wya to create a 3D SB at a given location
    if len(x_y_chanx_output_nodes) == 0 and len(x_y_chany_output_nodes) == 0 and len(x_plus_1_y_chanx_output_nodes) == 0 and len(x_y_plus_1_chany_output_nodes) == 0:
        return input_layer_none_nodes, output_layer_none_nodes, new_edges

    x_y_chanx_input_nodes_len = len(x_y_chanx_input_nodes)
    x_y_chany_input_nodes_len = len(x_y_chany_input_nodes)
    x_plus_1_y_chanx_input_nodes_len = len(x_plus_1_y_chanx_input_nodes)
    x_y_plus_1_chany_input_nodes_len = len(x_y_plus_1_chany_input_nodes)

    x_y_chanx_output_nodes_len = len(x_y_chanx_output_nodes)
    x_y_chany_output_nodes_len = len(x_y_chany_output_nodes)
    x_plus_1_y_chanx_output_nodes_len = len(x_plus_1_y_chanx_output_nodes)
    x_y_plus_1_chany_output_nodes_len = len(x_y_plus_1_chany_output_nodes)

    for i in range(max_output_len):
        input_nodes_to_send = []
        output_nodes_to_send = []

        if 0 < x_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chanx_input_nodes[j % x_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chanx_input_nodes[i % x_y_chanx_input_nodes_len])
        if 0 < x_y_chany_input_nodes_len:
            if max_crossings == -1 and x_y_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chany_input_nodes[j % x_y_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chany_input_nodes[i % x_y_chany_input_nodes_len])
        if 0 < x_plus_1_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_plus_1_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_plus_1_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[j % x_plus_1_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[i % x_plus_1_y_chanx_input_nodes_len])
        if 0 < x_y_plus_1_chany_input_nodes_len:
            if max_crossings == -1 and x_y_plus_1_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_plus_1_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[j % x_y_plus_1_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[i % x_y_plus_1_chany_input_nodes_len])

        if 0 < x_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_y_chanx_output_nodes[(i + 1) % x_y_chanx_output_nodes_len])
        if 0 < x_y_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_chany_output_nodes[(i + 1) % x_y_chany_output_nodes_len])
        if 0 < x_plus_1_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_plus_1_y_chanx_output_nodes[(i + 1) % x_plus_1_y_chanx_output_nodes_len])
        if 0 < x_y_plus_1_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_plus_1_chany_output_nodes[(i + 1) % x_y_plus_1_chany_output_nodes_len])


        input_layer_none_nodes_temp, output_layer_none_nodes_temp, new_edges_temp = connect_sb_nodes_combined(
            input_nodes_to_send, output_nodes_to_send, x, y, input_layer, output_layer)
        
        input_layer_none_nodes.extend(input_layer_none_nodes_temp)
        output_layer_none_nodes.extend(output_layer_none_nodes_temp)
        new_edges.extend(new_edges_temp)
    
    return input_layer_none_nodes, output_layer_none_nodes, new_edges

def create_wilton_2_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=-1):
    input_layer_none_nodes = []
    output_layer_none_nodes = []
    new_edges = []

    # If there are no outputs then there is no wya to create a 3D SB at a given location
    if len(x_y_chanx_output_nodes) == 0 and len(x_y_chany_output_nodes) == 0 and len(x_plus_1_y_chanx_output_nodes) == 0 and len(x_y_plus_1_chany_output_nodes) == 0:
        return input_layer_none_nodes, output_layer_none_nodes, new_edges

    x_y_chanx_input_nodes_len = len(x_y_chanx_input_nodes)
    x_y_chany_input_nodes_len = len(x_y_chany_input_nodes)
    x_plus_1_y_chanx_input_nodes_len = len(x_plus_1_y_chanx_input_nodes)
    x_y_plus_1_chany_input_nodes_len = len(x_y_plus_1_chany_input_nodes)

    x_y_chanx_output_nodes_len = len(x_y_chanx_output_nodes)
    x_y_chany_output_nodes_len = len(x_y_chany_output_nodes)
    x_plus_1_y_chanx_output_nodes_len = len(x_plus_1_y_chanx_output_nodes)
    x_y_plus_1_chany_output_nodes_len = len(x_y_plus_1_chany_output_nodes)

    for i in range(max_output_len):
        input_nodes_to_send = []
        output_nodes_to_send = []

        if 0 < x_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chanx_input_nodes[j % x_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chanx_input_nodes[i % x_y_chanx_input_nodes_len])
        if 0 < x_y_chany_input_nodes_len:
            if max_crossings == -1 and x_y_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chany_input_nodes[j % x_y_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chany_input_nodes[i % x_y_chany_input_nodes_len])
        if 0 < x_plus_1_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_plus_1_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_plus_1_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[j % x_plus_1_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[i % x_plus_1_y_chanx_input_nodes_len])
        if 0 < x_y_plus_1_chany_input_nodes_len:
            if max_crossings == -1 and x_y_plus_1_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_plus_1_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[j % x_y_plus_1_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[i % x_y_plus_1_chany_input_nodes_len])

        if 0 < x_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_y_chanx_output_nodes[(i + 1) % x_y_chanx_output_nodes_len])
        if 0 < x_y_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_chany_output_nodes[(i + 2) % x_y_chany_output_nodes_len])
        if 0 < x_plus_1_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_plus_1_y_chanx_output_nodes[(i + 3) % x_plus_1_y_chanx_output_nodes_len])
        if 0 < x_y_plus_1_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_plus_1_chany_output_nodes[(i + 4) % x_y_plus_1_chany_output_nodes_len])

        input_layer_none_nodes_temp, output_layer_none_nodes_temp, new_edges_temp = connect_sb_nodes_combined(
            input_nodes_to_send, output_nodes_to_send, x, y, input_layer, output_layer)
        
        input_layer_none_nodes.extend(input_layer_none_nodes_temp)
        output_layer_none_nodes.extend(output_layer_none_nodes_temp)
        new_edges.extend(new_edges_temp)
    
    return input_layer_none_nodes, output_layer_none_nodes, new_edges

def create_wilton_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=-1):
    input_layer_none_nodes = []
    output_layer_none_nodes = []
    new_edges = []

    # If there are no outputs then there is no wya to create a 3D SB at a given location
    if len(x_y_chanx_output_nodes) == 0 and len(x_y_chany_output_nodes) == 0 and len(x_plus_1_y_chanx_output_nodes) == 0 and len(x_y_plus_1_chany_output_nodes) == 0:
        return input_layer_none_nodes, output_layer_none_nodes, new_edges

    x_y_chanx_input_nodes_len = len(x_y_chanx_input_nodes)
    x_y_chany_input_nodes_len = len(x_y_chany_input_nodes)
    x_plus_1_y_chanx_input_nodes_len = len(x_plus_1_y_chanx_input_nodes)
    x_y_plus_1_chany_input_nodes_len = len(x_y_plus_1_chany_input_nodes)

    x_y_chanx_output_nodes_len = len(x_y_chanx_output_nodes)
    x_y_chany_output_nodes_len = len(x_y_chany_output_nodes)
    x_plus_1_y_chanx_output_nodes_len = len(x_plus_1_y_chanx_output_nodes)
    x_y_plus_1_chany_output_nodes_len = len(x_y_plus_1_chany_output_nodes)

    for i in range(max_output_len):

        input_nodes_to_send = []
        output_nodes_to_send = []

        if 0 < x_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chanx_input_nodes[(j) % x_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chanx_input_nodes[i % x_y_chanx_input_nodes_len])
        if 0 < x_y_chany_input_nodes_len:
            if max_crossings == -1 and x_y_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chany_input_nodes[(j + 1) % x_y_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chany_input_nodes[(i + 1) % x_y_chany_input_nodes_len])
        if 0 < x_plus_1_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_plus_1_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_plus_1_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[(j + 2) % x_plus_1_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[(i + 2) % x_plus_1_y_chanx_input_nodes_len])
        if 0 < x_y_plus_1_chany_input_nodes_len:
            if max_crossings == -1 and x_y_plus_1_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_plus_1_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[(j + 3) % x_y_plus_1_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[(i + 3) % x_y_plus_1_chany_input_nodes_len])

        if 0 < x_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_y_chanx_output_nodes[(i)% x_y_chanx_output_nodes_len])
        if 0 < x_y_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_chany_output_nodes[(i + 1)% x_y_chany_output_nodes_len])
        if 0 < x_plus_1_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_plus_1_y_chanx_output_nodes[(i + 2)% x_plus_1_y_chanx_output_nodes_len])
        if 0 < x_y_plus_1_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_plus_1_chany_output_nodes[(i + 3)% x_y_plus_1_chany_output_nodes_len])


        input_layer_none_nodes_temp, output_layer_none_nodes_temp, new_edges_temp = connect_sb_nodes_combined(input_nodes_to_send, output_nodes_to_send, x, y, input_layer, output_layer)
        input_layer_none_nodes += input_layer_none_nodes_temp
        output_layer_none_nodes += output_layer_none_nodes_temp
        new_edges += new_edges_temp
    
    return input_layer_none_nodes, output_layer_none_nodes, new_edges

def create_custom_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=-1, input_pattern=[0, 0, 0, 0], output_pattern=[0, 0, 0, 0]):
    '''
        This is a custom connection function that allows for a custom connection patterns to be used.
        The input pattern is a list of 4 integers that represent the number of inputs to be used for each input node.
        The output pattern is a list of 4 integers that represent the number of outputs to be used for each output node.

        The indices of the input pattern and output pattern are as follows:
        0: CHANX at location (x,y)
        1: CHANY at location (x,y)
        2: CHANX at location (x+1,y)
        3: CHANY at location (x,y+1)

        The pattern is as follows:
            Connection number i:

            Inputs:
                i + input_pattern[0] for CHANX at location (x,y)
                i + input_pattern[1] for CHANY at location (x,y)
                i + input_pattern[2] for CHANX at location (x+1,y)
                i + input_pattern[3] for CHANY at location (x,y+1)

            Outputs:
                i + output_pattern[0] for CHANX at location (x,y)
                i + output_pattern[1] for CHANY at location (x,y)
                i + output_pattern[2] for CHANX at location (x+1,y)
                i + output_pattern[3] for CHANY at location (x,y+1)

        The pattern is used to determine the input and output nodes offset to use for each connection.

        For example a subset connection would be:
            input_pattern = [0, 0, 0, 0]
            output_pattern = [0, 0, 0, 0]

        One way to do a wilton is:
            input_pattern = [0, 0, 0, 0]
            output_pattern = [1, 2, 3, 4]

    '''
    input_layer_none_nodes = []
    output_layer_none_nodes = []
    new_edges = []

    # If there are no outputs then there is no wya to create a 3D SB at a given location
    if len(x_y_chanx_output_nodes) == 0 and len(x_y_chany_output_nodes) == 0 and len(x_plus_1_y_chanx_output_nodes) == 0 and len(x_y_plus_1_chany_output_nodes) == 0:
        return input_layer_none_nodes, output_layer_none_nodes, new_edges

    x_y_chanx_input_nodes_len = len(x_y_chanx_input_nodes)
    x_y_chany_input_nodes_len = len(x_y_chany_input_nodes)
    x_plus_1_y_chanx_input_nodes_len = len(x_plus_1_y_chanx_input_nodes)
    x_y_plus_1_chany_input_nodes_len = len(x_y_plus_1_chany_input_nodes)

    x_y_chanx_output_nodes_len = len(x_y_chanx_output_nodes)
    x_y_chany_output_nodes_len = len(x_y_chany_output_nodes)
    x_plus_1_y_chanx_output_nodes_len = len(x_plus_1_y_chanx_output_nodes)
    x_y_plus_1_chany_output_nodes_len = len(x_y_plus_1_chany_output_nodes)

    for i in range(max_output_len):

        input_nodes_to_send = []
        output_nodes_to_send = []

        if 0 < x_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chanx_input_nodes[(j + input_pattern[0]) % x_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chanx_input_nodes[(i + input_pattern[0]) % x_y_chanx_input_nodes_len])
        if 0 < x_y_chany_input_nodes_len:
            if max_crossings == -1 and x_y_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_chany_input_nodes[(j + input_pattern[1]) % x_y_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_chany_input_nodes[(i + input_pattern[1]) % x_y_chany_input_nodes_len])
        if 0 < x_plus_1_y_chanx_input_nodes_len:
            if max_crossings == -1 and x_plus_1_y_chanx_input_nodes_len > max_output_len:
                for j in range(int(x_plus_1_y_chanx_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[(j + input_pattern[2]) % x_plus_1_y_chanx_input_nodes_len])
            else:
                input_nodes_to_send.append(x_plus_1_y_chanx_input_nodes[(i + input_pattern[2]) % x_plus_1_y_chanx_input_nodes_len])
        if 0 < x_y_plus_1_chany_input_nodes_len:
            if max_crossings == -1 and x_y_plus_1_chany_input_nodes_len > max_output_len:
                for j in range(int(x_y_plus_1_chany_input_nodes_len / max_output_len)):
                    input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[(j + input_pattern[3]) % x_y_plus_1_chany_input_nodes_len])
            else:
                input_nodes_to_send.append(x_y_plus_1_chany_input_nodes[(i + input_pattern[3]) % x_y_plus_1_chany_input_nodes_len])

        if 0 < x_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_y_chanx_output_nodes[(i + output_pattern[0])% x_y_chanx_output_nodes_len])
        if 0 < x_y_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_chany_output_nodes[(i + output_pattern[1])% x_y_chany_output_nodes_len])
        if 0 < x_plus_1_y_chanx_output_nodes_len:
            output_nodes_to_send.append(x_plus_1_y_chanx_output_nodes[(i + output_pattern[2])% x_plus_1_y_chanx_output_nodes_len])
        if 0 < x_y_plus_1_chany_output_nodes_len:
            output_nodes_to_send.append(x_y_plus_1_chany_output_nodes[(i + output_pattern[3])% x_y_plus_1_chany_output_nodes_len])


        input_layer_none_nodes_temp, output_layer_none_nodes_temp, new_edges_temp = connect_sb_nodes_combined(input_nodes_to_send, output_nodes_to_send, x, y, input_layer, output_layer)
        input_layer_none_nodes += input_layer_none_nodes_temp
        output_layer_none_nodes += output_layer_none_nodes_temp
        new_edges += new_edges_temp
    
    return input_layer_none_nodes, output_layer_none_nodes, new_edges

def create_combined_sb(input_nodes, output_nodes, x, y, input_layer, output_layer, connection_type="subset", vertical_connectivity_percentage=1, max_number_of_crossings=-1):
    # need to figure out which nodes to connect together for larger than 2 CWs

    accepted_connection_types = ["subset", "wilton", "wilton_2", "wilton_3", "custom"]

    assert(connection_type in accepted_connection_types)

    # The way it works is by ptc, intially using a subset connection pattern for interlayer connections
    # To do this need to find the appropriate nodes to connect together based on the ptc value
    # For inputs:
    #   - (x, y) CHANs have even ptc values starting from 0 and increasing
    #   - (x + 1, y) & (x, y+1) CHANs have odd ptc values starting from 1 and increasing
    # For outputs:
    #   - (x, y) CHANs have odd ptc values starting from 1 and increasing
    #   - (x + 1, y) & (x, y+1) CHANs have even ptc values starting from 0 and increasing

    # need to connect for example: 
    # inputs:
    #   CHANX (x, y) with ptc: 0
    #   CHANX (x + 1, y) with ptc: 1
    #   CHANY (x, y) with ptc: 0
    #   CHANY (x, y + 1) with ptc: 1
    # outputs:
    #   CHANX (x, y) with ptc: 1
    #   CHANX (x + 1, y) with ptc: 0
    #   CHANY (x, y) with ptc: 1
    #   CHANY (x, y + 1) with ptc: 0

    # First store the nodes in a list with increasing ptc values
    x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes = sort_chan_nodes_by_direction(input_nodes, x, y)

    x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes = sort_chan_nodes_by_direction(output_nodes, x, y)

    #Print different lens for debugging
    # print_verbose(f"{'*' * 10}")
    # print_verbose(f"X: {x} Y: {y} Input Layer: {input_layer} Output Layer: {output_layer}")
    # print_verbose(f"Input Nodes:                  {len(input_nodes)}                  Output Nodes: {len(output_nodes)}")

    # print_verbose(f"x_y_chanx_input_nodes:        {len(x_y_chanx_input_nodes)}        x_y_chanx_output_nodes: {len(x_y_chanx_output_nodes)}")   
    # print_verbose(f"x_y_chany_input_nodes:        {len(x_y_chany_input_nodes)}        x_y_chany_output_nodes: {len(x_y_chany_output_nodes)}")    
    # print_verbose(f"x_plus_1_y_chanx_input_nodes: {len(x_plus_1_y_chanx_input_nodes)} x_plus_1_y_chanx_output_nodes: {len(x_plus_1_y_chanx_output_nodes)}")
    # print_verbose(f"x_y_plus_1_chany_input_nodes: {len(x_y_plus_1_chany_input_nodes)} x_y_plus_1_chany_output_nodes: {len(x_y_plus_1_chany_output_nodes)}")

    # print_verbose(f"{'*' * 10}")    
    # print_verbose(f"x_y_chanx_input_nodes:  {x_y_chanx_input_nodes}")
    # print_verbose(f"x_y_chanx_output_nodes: {x_y_chanx_output_nodes}")

    # print_verbose(f"{'*' * 5}")
    # print_verbose(f"x_y_chany_input_nodes:  {x_y_chany_input_nodes}")
    # print_verbose(f"x_y_chany_output_nodes: {x_y_chany_output_nodes}")

    # print_verbose(f"{'*' * 5}")
    # print_verbose(f"x_plus_1_y_chanx_input_nodes:  {x_plus_1_y_chanx_input_nodes}")
    # print_verbose(f"x_plus_1_y_chanx_output_nodes: {x_plus_1_y_chanx_output_nodes}")

    # print_verbose(f"{'*' * 5}")    
    # print_verbose(f"x_y_plus_1_chany_input_nodes:  {x_y_plus_1_chany_input_nodes}")
    # print_verbose(f"x_y_plus_1_chany_output_nodes: {x_y_plus_1_chany_output_nodes}")

    # assert len(x_y_chanx_input_nodes) == len(x_y_chanx_output_nodes)
    # assert len(x_y_chany_input_nodes) == len(x_y_chany_output_nodes)
    # assert len(x_plus_1_y_chanx_input_nodes) == len(x_plus_1_y_chanx_output_nodes)
    # assert len(x_y_plus_1_chany_input_nodes) == len(x_y_plus_1_chany_output_nodes)

    max_output_len = int(max(len(x_y_chanx_output_nodes), len(x_y_chany_output_nodes), len(x_plus_1_y_chanx_output_nodes), len(x_y_plus_1_chany_output_nodes)) * vertical_connectivity_percentage)

    if connection_type == "subset":
        return create_subset_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=max_number_of_crossings)
    elif connection_type == "wilton":
        return create_wilton_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=max_number_of_crossings)
    elif connection_type == "wilton_2":
        return create_wilton_2_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=max_number_of_crossings)
    elif connection_type == "wilton_3":
        return create_wilton_3_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=max_number_of_crossings)
    elif connection_type == "custom":
        return create_custom_connection_3d_sb(max_output_len, x_y_chanx_input_nodes, x_y_chany_input_nodes, x_plus_1_y_chanx_input_nodes, x_y_plus_1_chany_input_nodes, x_y_chanx_output_nodes, x_y_chany_output_nodes, x_plus_1_y_chanx_output_nodes, x_y_plus_1_chany_output_nodes, x, y, input_layer, output_layer, max_crossings=max_number_of_crossings, input_pattern=args.sb_input_pattern, output_pattern=args.sb_output_pattern)

def sb_coord_grid(file_path, grid_x, grid_y):
    '''
        Function to read coords if user specifies custom SB location using CSV file.
        The bottom left corner of the grid is (0, 0) and the top right corner is (width-1, height-1).
        The Y direction is vertical and the X direction is horizontal.

        The csv file only contains the SB locations, with "x" indicating a SB location and "o" indicating no SB location.
        
        An example csv file contents for a 4x4 grid:
        ```
            o,o,o,o
            o,o,x,o
            o,x,o,o
            o,o,o,o
        ```

    '''
    
    coords = []
    with open(file_path, 'r') as file:
        # Read all lines
        lines = file.readlines()
        # Reverse the lines to make bottom row y=0
        lines.reverse()

        max_y = len(lines)

        if max_y != grid_y + 1:
            print("Error: The number of rows in the CSV file does not match the grid size of the FPGA.")
            exit(1)
        
        for y, line in enumerate(lines):
            # Split the line by comma and remove whitespace/newlines
            row = [cell.strip() for cell in line.split(',')]

            max_row_x = len(row)
            if max_row_x != grid_x + 1:
                print("Error: The number of columns in the CSV file does not match the grid size of the FPGA.")
                exit(1)

            for x, cell in enumerate(row):
                if cell == 'x':
                    coords.append((x, y))
    return coords

def percentage_rows(grid_x, grid_y, percent):
    """
    Return a percentage of evenly spaced rows from a 2D grid.
    
    :param grid_x: The range or size of the x-dimension.
    :param grid_y: The range or size of the y-dimension.
    :param percent: The percentage of rows to include (0.0 to 1.0).
    :return: List of coordinates (x, y) from the selected rows.
    """
    assert 0 <= percent <= 1, "Percent must be between 0 (inclusive) and 1 (inclusive)."
    
    # Calculate how many rows to select
    rows_to_select = max(1, round((grid_y + 1) * percent))
    
    # Select evenly spaced row indices
    if rows_to_select == grid_y + 1:  # If all rows are selected
        row_indices = range(grid_y + 1)
    else:
        row_indices = np.linspace(0, grid_y, rows_to_select, dtype=int)
    
    # Generate coordinates for each selected row
    ret = []
    for y in row_indices:
        for x in range(grid_x + 1):
            ret.append((x, y))
    
    return ret

def percentage_columns(grid_x, grid_y, percent):
    """
    Return a percentage of evenly spaced columns from a 2D grid.
    
    :param grid_x: The range or size of the x-dimension.
    :param grid_y: The range or size of the y-dimension.
    :param percent: The percentage of columns to include (0.0 to 1.0).
    :return: List of coordinates (x, y) from the selected columns.
    """
    assert 0 <= percent <= 1, "Percent must be between 0 (inclusive) and 1 (inclusive)."
    
    # Calculate how many columns to select
    cols_to_select = max(1, round((grid_x + 1) * percent))
    
    # Select evenly spaced column indices
    if cols_to_select == grid_x + 1:  # If all columns are selected
        col_indices = range(grid_x + 1)
    else:
        col_indices = np.linspace(0, grid_x, cols_to_select, dtype=int)
    
    # Generate coordinates for each selected column
    ret = []
    for x in col_indices:
        for y in range(grid_y + 1):
            ret.append((x, y))
    
    return ret

def percentage_core(grid_x, grid_y, percent):
    """
    Return a square-shaped core from the center of the grid based on percentage.
    Creates a square pattern starting from the center and expanding outward.
    """
    assert 0 <= percent <= 1, "Percent must be between 0 (inclusive) and 1 (inclusive)."
    
    total_elements = (grid_x + 1) * (grid_y + 1)
    elements_to_include = round(total_elements * percent)
    
    # Find center of grid
    center_x = grid_x // 2
    center_y = grid_y // 2
    
    # Calculate max Chebyshev distance (max of |x-center_x|, |y-center_y|)
    all_coords = [(x, y) for x in range(grid_x + 1) for y in range(grid_y + 1)]
    chebyshev_distances = [max(abs(x - center_x), abs(y - center_y)) for x, y in all_coords]
    
    # Sort coordinates by Chebyshev distance from center (increasing)
    # This creates square-shaped layers expanding from the center
    sorted_coords = [coord for _, coord in sorted(zip(chebyshev_distances, all_coords))]
    
    return sorted_coords[:elements_to_include]

def percentage_perimeter(grid_x, grid_y, percent):
    """
    Return a square-shaped perimeter around the grid based on percentage.
    Creates a square pattern starting from the outside and moving inward.
    """
    assert 0 <= percent <= 1, "Percent must be between 0 (inclusive) and 1 (inclusive)."
    
    total_elements = (grid_x + 1) * (grid_y + 1)
    elements_to_include = round(total_elements * percent)
    
    # Find center of grid
    center_x = grid_x // 2
    center_y = grid_y // 2
    
    # Calculate max Chebyshev distance (max of |x-center_x|, |y-center_y|)
    all_coords = [(x, y) for x in range(grid_x + 1) for y in range(grid_y + 1)]
    chebyshev_distances = [max(abs(x - center_x), abs(y - center_y)) for x, y in all_coords]
    
    # Sort coordinates by Chebyshev distance from center (decreasing)
    # This creates square-shaped layers from the outside inward
    sorted_coords = [coord for _, coord in sorted(zip(chebyshev_distances, all_coords), reverse=True)]
    
    return sorted_coords[:elements_to_include]

def percentage_skip_repeated_interval(grid_x, grid_y, percent):
    """
    Iterate over a 2D grid in a deterministic pattern, skipping elements
    based on the specified percentage.
    :param grid_x: The range or size of the x-dimension.
    :param grid_y: The range or size of the y-dimension.
    :param percent: The percentage of elements to skip (0.0 to 1.0).
    :yield: Coordinates (x, y) that meet the percentage criteria.
    """
    assert 0 <= percent <= 1, "Percent must be between 0 (inclusive) and 1 (exclusive)."
    
    # Flatten the 2D grid into a linear list of indices
    all_coords = [(x, y) for x in range(grid_x + 1) for y in range(grid_y + 1)]
    total_elements = len(all_coords)
    
    true_count = round(total_elements * percent)
    indices = np.linspace(0, total_elements - 1, true_count, dtype=int)

    ret = []

    for i in indices:
        ret.append(all_coords[i])
    return ret

def percentage_skip_random(grid_x, grid_y, percent):
    """
    Iterate over a 2D grid while ensuring a percentage of elements are skipped.
    :param grid_x: The range or size of the x-dimension.
    :param grid_y: The range or size of the y-dimension.
    :param percent: The percentage of elements to skip (0.0 to 1.0).
    :yield: Coordinates (x, y) that meet the percentage criteria.
    """
    assert 0 <= percent <= 1, "Percent must be between 0 and 1 (inclusive)."
    
    total_elements = (grid_x + 1) * (grid_y + 1)
    num_to_keep = int(total_elements * (percent))

    # Randomly sample a subset of coordinates to keep
    all_coords = [(x, y) for x in range(grid_x + 1) for y in range(grid_y + 1)]
    selected_coords = random.sample(all_coords, num_to_keep)

    return selected_coords

def skip_loop(grid_x, grid_y, percent):
    pattern_type = args.sb_location_pattern

    coords = []

    if pattern_type == "repeated_interval":
        coords = percentage_skip_repeated_interval(grid_x, grid_y, percent)
    elif pattern_type == "random":
        coords = percentage_skip_random(grid_x, grid_y, percent)
    elif pattern_type == 'rows':
        coords = percentage_rows(grid_x, grid_y, percent)
    elif pattern_type == 'columns':
        coords = percentage_columns(grid_x, grid_y, percent)
    elif pattern_type == 'core':
        coords = percentage_core(grid_x, grid_y, percent)
    elif pattern_type == 'perimeter':
        coords = percentage_perimeter(grid_x, grid_y, percent)
    elif pattern_type == "custom":
        coords = sb_coord_grid(args.sb_grid_csv, grid_x, grid_y)

    for coord in coords:
        yield coord

def create_sb(structure, connection_type="subset", vertical_connectivity_percentage=1, base_rrg_path="", output_rrg_path=""):
    print_verbose("Creating SB connections")
    
    start_time = time.time()
    # loop over the device and find the highest CHAN x and y
    # device_x, device_y, num_layers = find_device_chan_dim()

    # only create sbs for every other location
    global percent_connectitivty

    edges_to_write = []
    nodes_to_write = []

    num_created = 0

    global device_max_x, device_max_y, device_max_layer

    max_vertical_crossings = args.max_number_of_crossings

    number_sbs = device_max_x * device_max_y * percent_connectitivty
    print_iter = round(number_sbs / 5)
    # For each location, find all relevant chans that either enter or exit th SB
    for x, y in skip_loop(device_max_x, device_max_y, percent_connectitivty):

        # print_verbose(f"{'*' * 60}")
        # print_verbose("Creating SB for x:", x, "y:", y)
        

        num_created += 1

        # chan_nodes = find_chan_nodes(x, y)

        # layer_0_sb_input_nodes, layer_0_sb_output_nodes, layer_1_sb_input_nodes, layer_1_sb_output_nodes = sort_chan_nodes_into_input_and_output(chan_nodes, x, y)

        # input_layer_0_none_nodes = []
        # output_layer_1_none_nodes = []
        # input_layer_1_none_nodes = []
        # output_layer_0_none_nodes = []
        # new_edges_0 = []
        # new_edges_1 = []

        # input_layer_0_none_nodes, output_layer_1_none_nodes, new_edges_0 = create_combined_sb(layer_0_sb_input_nodes, layer_1_sb_output_nodes, x, y, 0, 1, connection_type, vertical_connectivity_percentage, max_number_of_crossings=max_vertical_crossings)
        # input_layer_1_none_nodes, output_layer_0_none_nodes, new_edges_1 = create_combined_sb(layer_1_sb_input_nodes, layer_0_sb_output_nodes, x, y, 1, 0, connection_type, vertical_connectivity_percentage, max_number_of_crossings=max_vertical_crossings)

        for n in range(1, device_max_layer + 1):
            m = n - 1

            # print_verbose(f"{'*' * 60}")
            # print_verbose(f"Creating SB connections between layer {n} and layer {m} at x: {x} y: {y}")
            # print_verbose(f"{'*' * 40}")

            # 1. Find nodes at layer n and n-1 (n-1 layer is refered to as layer m)
            #    * Note: M doesnt have to be n-1, it can be any layer, if user wants to create a connection for a SB that spans more than 1 layer
            #    * For example: A bypass SB connection that connects layer 0 to layer 2 directly without having to go through a mux at layer 1
            chan_nodes = find_chan_nodes(x, y, n, m)
            
            # 2. Sort nodes into input and output for layer n and m
            layer_m_sb_input_nodes, layer_m_sb_output_nodes, layer_n_sb_input_nodes, layer_n_sb_output_nodes = sort_chan_nodes_into_input_and_output(chan_nodes, x, y, n)
            
            # 3. Create Connection where layer m nodes are inputs and layer n nodes are outputs
            input_layer_m_none_nodes, output_layer_n_none_nodes, new_edges_0 = create_combined_sb(layer_m_sb_input_nodes, layer_n_sb_output_nodes, x, y, m, n, connection_type, vertical_connectivity_percentage, max_number_of_crossings=max_vertical_crossings)
            
            # 4. Create Connection where layer n nodes are inputs and layer m nodes are outputs
            input_layer_n_none_nodes, output_layer_m_none_nodes, new_edges_1 = create_combined_sb(layer_n_sb_input_nodes, layer_m_sb_output_nodes, x, y, n, m, connection_type, vertical_connectivity_percentage, max_number_of_crossings=max_vertical_crossings)
            
            # 5. Make print statements for debugging
            # print_verbose(f"Created {len(input_layer_m_none_nodes)} input none nodes for layer {m} connection to layer {n}")
            # print_verbose(f"Created {len(output_layer_n_none_nodes)} output none nodes for layer {n} connection to layer {m}")
            # print_verbose(f"Created {len(input_layer_n_none_nodes)} input none nodes for layer {n} connection to layer {m}")
            # print_verbose(f"Created {len(output_layer_m_none_nodes)} output none nodes for layer {m} connection to layer {n}")

            # print_verbose(f"Created {len(new_edges_0)} edges to connect layer {m} to layer {n}")
            # print_verbose(f"Created {len(new_edges_1)} edges to connect layer {n} to layer {m}")

            # 6. Extened the nodes and edges to write
            nodes_to_write.extend(input_layer_m_none_nodes)
            nodes_to_write.extend(output_layer_n_none_nodes)
            nodes_to_write.extend(input_layer_n_none_nodes)
            nodes_to_write.extend(output_layer_m_none_nodes)

            edges_to_write.extend(new_edges_0)
            edges_to_write.extend(new_edges_1)

        # print_verbose(f"{'*' * 10}")

        # print_verbose(f"Created {len(input_layer_0_none_nodes)} input none nodes for layer 0 ")
        # print_verbose(f"Created {len(output_layer_0_none_nodes)} output none nodes for none nodes for layer 1")
        # print_verbose(f"Created {len(input_layer_1_none_nodes)} input none nodes for layer 1")
        # print_verbose(f"Created {len(output_layer_1_none_nodes)} output none nodes for layer 0")

        # nodes_to_write.extend(input_layer_0_none_nodes)
        # nodes_to_write.extend(output_layer_1_none_nodes)
        # nodes_to_write.extend(input_layer_1_none_nodes)
        # nodes_to_write.extend(output_layer_0_none_nodes)

        # print_verbose(f"Created {len(new_edges_0)} edges to connect layer 0 to layer 1")
        # print_verbose(f"Created {len(new_edges_1)} edges to connect layer 1 to layer 0")

        # edges_to_write.extend(new_edges_0)
        # edges_to_write.extend(new_edges_1)

        

        if num_created % print_iter == 0:
            print_verbose(f"Created {round((num_created / number_sbs) * 100)}% of 3D SBs")

        # print_verbose("added", len(nodes_to_write) - node_count_before, "nodes to make", total_size((nodes_to_write, node_data, node_index)) / (1024 * 1024 * 1024), "GiB, added", len(edges_to_write) - edge_count_before, "edges to make", total_size((edges_to_write, edge_data, edges_by_src, edges_by_sink)) / (1024 * 1024 * 1024), "GiB")
    
    print_verbose(f"\nNumber of new nodes: {len(nodes_to_write)}")
    print_verbose(f"Number of new edges: {len(edges_to_write)}\n")

    print_verbose("Sorting Nodes")
    sorting_start_time = time.time()
    nodes_to_write = sort_nodes(nodes_to_write)
    sorting_end_time = time.time()

    print_verbose(f"Sorting Nodes took { ((sorting_end_time - sorting_start_time) * 1000):0.2f} ms")

    print_verbose("Writing SB Nodes and Edges")
    writing_start_time = time.time()
    # write_sb_nodes(structure, nodes_to_write)
    # write_sb_edges(structure, edges_to_write)
    write_sb_nodes_and_edges_streaming_simple(base_rrg_path, output_rrg_path, nodes_to_write, edges_to_write)


    writing_end_time = time.time()
    print_verbose(f"Writing SB Nodes and Edges took { ((writing_end_time - writing_start_time) * 1000):0.2f} ms")

    end_time = time.time()
    print_verbose(f"Creating SB connections took { ((end_time - start_time) * 1000):0.2f} ms")

    print_verbose(f"Total number of SBs created: {num_created}")

def extract_switch_and_segment(structure, segment_name, switch_name):
    global pattern_dict
    switch_list = structure.find('switches')

    found_switch = False
    found_segment = False

    for switch in switch_list.findall('switch'):
        name = switch.get('name')
        if name == switch_name:
            global switch_id
            switch_id = int(switch.get('id'))
            found_switch = True
            break

    if not found_switch and switch_name != "":
        print(f"ERROR: Switch {switch_name} not found in architecture file.")
        exit(1)

    segment_list = structure.find('segments')

    for segment in segment_list.findall('segment'):
        name = segment.get('name')
        id = int(segment.get('id'))
        if name == segment_name:
            global segment_id
            segment_id = id
            found_segment = True
        
        
        pattern_dict[id] = pattern_dict.pop(name)

    if not found_segment and segment_name != "":
        print(f"ERROR: Segment {segment_name} not found in architecture file.")
        exit(1)

def extract_switches_and_segments_streaming(file_path, segment_name, switch_name):
    """
    Extract only switches and segments, return early without processing nodes
    """
    global switch_id, segment_id, pattern_dict, switch_str_to_id, segment_str_to_id, segment_to_mux_str, segment_to_mux_id
    
    parser = etree.iterparse(
        file_path,
        events=('start', 'end'),
        huge_tree=True
    )
    
    in_switches = False
    in_segments = False
    found_switch = False
    found_segment = False
    segments_done = False
    
    for event, elem in parser:
        # Process switches
        if event == 'start' and elem.tag == 'switches':
            in_switches = True
        elif event == 'end' and elem.tag == 'switches':
            in_switches = False
            if not found_switch and switch_name != "":
                print(f"ERROR: Switch {switch_name} not found in architecture file.")
                exit(1)
            elem.clear()
        elif event == 'end' and elem.tag == 'switch' and in_switches:
            name = elem.get('name')
            if name == switch_name:
                switch_id = int(elem.get('id'))
                found_switch = True
            switch_str_to_id[name] = int(elem.get('id'))
            elem.clear()
        
        # Process segments
        elif event == 'start' and elem.tag == 'segments':
            in_segments = True
        elif event == 'end' and elem.tag == 'segments':
            in_segments = False
            segments_done = True
            if not found_segment and segment_name != "":
                print(f"ERROR: Segment {segment_name} not found in architecture file.")
                exit(1)
            elem.clear()
        elif event == 'end' and elem.tag == 'segment' and in_segments:
            name = elem.get('name')
            id_val = int(elem.get('id'))
            
            if name in pattern_dict:
                pattern_dict[id_val] = pattern_dict.pop(name)
            
            if name == segment_name:
                segment_id = id_val
                found_segment = True
            segment_str_to_id[name] = id_val
            elem.clear()
        
        # Once we've processed both switches and segments, we can stop
        if segments_done and (found_switch or switch_name == "") and (found_segment or segment_name == ""):
            break
        
        # Clean up any other elements we encounter
        if event == 'end':
            elem.clear()

        # Process Segment to Mux Mapping (Convert from string to id)
    for seg_name, mux_name in segment_to_mux_str.items():
        if seg_name in segment_str_to_id and mux_name in switch_str_to_id:
            segment_to_mux_id[str(segment_str_to_id[seg_name])] = str(switch_str_to_id[mux_name])
        else:
            print(f"ERROR: Segment {seg_name} or Mux {mux_name} not found in architecture file.")
            exit(1)

def parse_arch_xml(arch_file):
    '''
    Function to parse the architecture XML file. It looks for the SB connection pattern of the segments in the architecture.
    As well as the segment id and the switch id for the 3D SBs (if defined by user), else it uses the first segment and switch it finds.
    '''
    global pattern_dict
    global segment_to_mux_str
    print_verbose(f"Reading Architecture File: {arch_file}")
    parser = etree.XMLParser(
            remove_blank_text=True,
            remove_comments=True,
            collect_ids=False,
            huge_tree=True,  # Allows for larger trees
            resolve_entities=False  # Saves some memory
        )

    arch_tree = etree.parse(arch_file, parser)
    arch_root = arch_tree.getroot()

    

    segment_list = arch_root.find("segmentlist")

    for segment in segment_list.findall("segment"):
        name = segment.get("name")
        pattern = segment.find("sb").text
        pattern = pattern.split(" ")
        pattern_dict[name] = [True if x == "1" else False for x in pattern]
        segment_to_mux_str[name] = segment.find("mux").get("name")

def main():
    start_time = time.time()
    
    file_path = args.input_file
    output_file_path = args.output_path

    global percent_connectitivty
    percent_connectitivty = args.percent_connectivity

    connection_type = args.connection_type.lower()

    if connection_type == "custom":
        input_pat = args.sb_input_pattern
        if input_pat == None:
            print("ERROR: Custom connection pattern specified but no input pattern provided. Input and Output pattern are required for custom connection.")
            exit(1)

        output_pat = args.sb_output_pattern
        if output_pat == None:
            print("ERROR: Custom connection pattern specified but no output pattern provided. Input and Output pattern are required for custom connection.")
            exit(1)

        if len(input_pat) != 4 or len(output_pat) != 4:
            print("ERROR: Custom connection pattern must be of length 4.")
            exit(1)

    vertical_connectivity_percentage = args.vertical_connectivity_percentage

    arch_file = args.arch_file
    segment_name = args.sb_3d_segment
    switch_name = args.sb_3d_switch

    global verbose

    verbose = args.verbose

    sb_location_pattern = args.sb_location_pattern
    if sb_location_pattern == "custom":
        sb_grid_csv = args.sb_grid_csv
        if sb_grid_csv == "":
            print("ERROR: Custom SB location pattern specified but no CSV file provided.")
            exit(1)

    parse_arch_xml(arch_file)

    design_string = f"{file_path} with {(percent_connectitivty * 100):0.1f} SBs, connection type: {connection_type}, vertical connectivity percentage: {vertical_connectivity_percentage} outputting to {output_file_path}"

    print(f"Creating 3D SBs for {design_string}")

    parser = etree.XMLParser(
            remove_blank_text=True,
            remove_comments=True,
            collect_ids=False,
            huge_tree=True,  # Allows for larger trees
            resolve_entities=False  # Saves some memory
        )

    # structure, tree = read_structure(file_path, parser)

    # extract_switch_and_segment(structure, segment_name, switch_name)

    # extract_nodes(structure)

    read_structure_streaming(file_path)
    extract_switches_and_segments_streaming(file_path, segment_name, switch_name)

    create_sb(None, connection_type, vertical_connectivity_percentage, base_rrg_path=file_path, output_rrg_path=output_file_path)

    # tree.write(output_file_path, pretty_print=False, xml_declaration=True, encoding="UTF-8", compression=None)

    end_time = time.time()
    print(f"Generating SBs took { ((end_time - start_time) * 1000):0.2f} ms")

if __name__ == "__main__":
    main()

