import os
import logging
from pathlib import Path
import utils.macro_expand as macro_expand
import utils.doxygen_extractor as doxygen_extractor
import utils.header_extractor as HeaderExtractor
import glob
import json
import re
from collections import defaultdict, deque
from tqdm import tqdm
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def process_macro_expansion(project_path:str)->str:
    project_path = Path(project_path)
    expanded_dir = project_path.parent / f"{project_path.name}_expanded"
    if not expanded_dir.exists() or not any(expanded_dir.iterdir()):
        macro_expand.create_compile_commands(project_path) # genereate compile_command.json
        macro_expand.expand_macros(project_path, expanded_dir) # use the compile_command to expand macro
    
    expanded_dealed_dir = project_path.parent / f"{project_path.name}_expanded_dealed"
    if not expanded_dealed_dir.exists() or not any(expanded_dealed_dir.iterdir()):
        expanded_dealed_dir = macro_expand.format_start(expanded_dir) # tag the code from the System or Local
        # macro_expand.header_extractor(expanded_dealed_dir) # extract the header info to the "include.h"
        macro_expand.compile_c_files(expanded_dealed_dir)
    return str(expanded_dealed_dir)
  
# Remove all the declaration|struct|enum|union|typedef to a `.h` file  
def extract_header_info(expanded_dir:str)->str:
    expanded_dir = Path(expanded_dir)
    expanded_processed_dir = expanded_dir.parent / f"{expanded_dir.name}_dealed"
    if expanded_processed_dir.exists() and list(expanded_processed_dir.glob("*.c")):
        logger.info(f"extract_header_info directory already exists: {expanded_processed_dir}")
        return str(expanded_processed_dir)
    
    os.makedirs(expanded_processed_dir, exist_ok=True)
        
    header_extractor = HeaderExtractor.HeaderExtractor()
    header_extractor.start_parser(str(expanded_dir), str(expanded_processed_dir))
    
    # Verify that there are no errors with `gcc-c`
    header_extractor.compile_c_files(str(expanded_processed_dir))
    
    return str(expanded_processed_dir)


# Using the doxygen to generate call graph of the C proejct
def extract_doxygen_info(expanded_processed_dir:str, parsed_project_path:str)->tuple[str, str]:
    project_name = os.path.basename(expanded_processed_dir)
    os.makedirs(parsed_project_path, exist_ok=True)
    entities_path = os.path.join(parsed_project_path, f"{project_name}_entities.json")
    relationships_path = os.path.join(parsed_project_path, f"{project_name}_relationships.json")
    if os.path.exists(entities_path) and os.path.exists(relationships_path):
        logger.info(f"extract_doxygen_info directory already exists: {entities_path} and {relationships_path}")
        return entities_path, relationships_path
    
    xml_dir = os.path.join(expanded_processed_dir, 'doxygen_output', 'xml')
    if os.path.exists(os.path.join(xml_dir, 'index.xml')):
        logger.info(f"Reusing existing Doxygen XML directory: {xml_dir}")
    else:
        xml_dir = doxygen_extractor.setup_doxygen(expanded_processed_dir, project_name)

    doxygen_parser = doxygen_extractor.DoxygenXmlParser(xml_dir, entities_path=entities_path, relationships_path=relationships_path, project_dir=expanded_processed_dir)
    if os.path.exists(entities_path):
        logger.info(f"Reusing existing entities file: {entities_path}")
    else:
        # Extract `entity` from the index.
        doxygen_parser._extract_entities_from_index()

    if os.path.exists(relationships_path):
        logger.info(f"Reusing existing relationships file: {relationships_path}")
    else:
        # Extract `relationship` from the xml. This step has its own partial checkpoint.
        doxygen_parser._extract_relationships_from_xml()
    return entities_path, relationships_path



def extract_call_graph(entities_path:str, relationships_path:str)->str:
    """
    Output format: {caller_id: [callee_id1, callee_id2, ...]}
    """
    with open(entities_path, 'r', encoding='utf-8') as f:
        entities_list = json.load(f)
    with open(relationships_path, 'r', encoding='utf-8') as f:
        relationships_list = json.load(f)
    
    call_graph = defaultdict(list)
    for entity in tqdm(entities_list, desc="Extracting call graph"):
        if "SYSTEM" in entity['is_system']: continue
        source_unique_name = entity['unique_name']
        
        all_dependencies = []
        for relationship in relationships_list:
            if relationship['source_unique_name'] == source_unique_name:
                target_unique_name = relationship['target_unique_name']
                for dep_entity in entities_list:
                    if dep_entity['unique_name'] == target_unique_name and "LOCAL" in dep_entity['is_system']:
                        all_dependencies.append(dep_entity['unique_name'])
        call_graph[source_unique_name] = all_dependencies
    return call_graph


def topological_sort_call_graph(call_graph):
    # Step 1: Find all strongly connected components (cycles)
    def find_sccs(graph):
        # Kosaraju's algorithm for finding strongly connected components
        
        # First DFS to fill the stack with nodes in order of finish time
        visited = set()
        stack = []
        
        def dfs1(node):
            visited.add(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs1(neighbor)
            stack.append(node)
        
        # Run first DFS for all nodes
        for node in graph:
            if node not in visited:
                dfs1(node)
        
        # Create reversed graph
        reversed_graph = defaultdict(list)
        for node, neighbors in graph.items():
            for neighbor in neighbors:
                reversed_graph[neighbor].append(node)
        
        # Second DFS to find SCCs
        visited.clear()
        sccs = []
        
        def dfs2(node, component):
            visited.add(node)
            component.append(node)
            for neighbor in reversed_graph.get(node, []):
                if neighbor not in visited:
                    dfs2(neighbor, component)
        
        # Process nodes in reverse order of finish time
        while stack:
            node = stack.pop()
            if node not in visited:
                component = []
                dfs2(node, component)
                sccs.append(component)
        
        return sccs
    
    # Find all strongly connected components
    sccs = find_sccs(call_graph)
    
    # Create a mapping from node to its SCC
    node_to_scc = {}
    for i, scc in enumerate(sccs):
        for node in scc:
            node_to_scc[node] = i
    
    # Create a new graph where each SCC is a single node
    # Important: The edges should represent "is called by" relationship for correct topological order
    condensed_graph = defaultdict(list)
    
    for caller, callees in call_graph.items():
        caller_scc_id = node_to_scc[caller]
        for callee in callees:
            callee_scc_id = node_to_scc[callee]
            # Only add edge if it's between different SCCs
            if caller_scc_id != callee_scc_id and caller_scc_id not in condensed_graph[callee_scc_id]:
                # Add edge from callee to caller (reverse direction)
                condensed_graph[callee_scc_id].append(caller_scc_id)
    
    # Perform topological sort on the condensed graph
    in_degree = {scc_id: 0 for scc_id in range(len(sccs))}
    for scc_id, neighbors in condensed_graph.items():
        for neighbor in neighbors:
            in_degree[neighbor] += 1
    
    # Start with nodes that have no incoming edges
    queue = deque([scc_id for scc_id, degree in in_degree.items() if degree == 0])
    topo_order = []
    
    while queue:
        current = queue.popleft()
        topo_order.append(current)
        
        for neighbor in condensed_graph.get(current, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    # Convert the SCC IDs back to the original nodes
    # If an SCC has multiple nodes, return them as a tuple
    result = []
    for scc_id in topo_order:
        component = sccs[scc_id]
        if len(component) > 1:
            # This is a cycle, return as tuple
            result.append(tuple(component))
        else:
            # Single node, return as is
            result.append(component[0])
    
    # Check if we have a valid topological sort
    if len(topo_order) != len(sccs):
        print("Warning: The condensed graph still contains cycles")
    
    return result


def check_for_main(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            pattern = r'(int|void)\s+main\s*\('
            return bool(re.search(pattern, content))
    except:
        return False
        
        
def obtain_project_tree(pathList, root_path, indent=""):
    ignore_dirs = {"doxygen_output"}
    ignore_files = {
        "Doxyfile",  
        ".tag",     
    }
    
    entries = os.listdir(root_path)


    entries = [e for e in entries if (
        e not in ignore_dirs and  
        e not in ignore_files and  
        (os.path.isdir(os.path.join(root_path, e)) or  
         e.endswith(('.c', '.h'))) 
    )]
    
    entries.sort()  

    for index, entry in enumerate(entries):
        full_path = os.path.join(root_path, entry)
        is_last = index == len(entries) - 1  
        
        if entry.endswith('.c') and check_for_main(full_path):
            entry_text = f"{entry} [Contain *main* Function]"
        else:
            entry_text = entry
        
        if is_last:
            pathList.append(f"{indent}└── {entry_text}")
            new_indent = indent + "    " 
        else:
            pathList.append(f"{indent}├── {entry_text}")
            new_indent = indent + "│   "  

        if os.path.isdir(full_path):
            obtain_project_tree(pathList, full_path, new_indent)




def write_projectInfo(project_tree:list, call_graph:dict, topo_order:list,  output_projectInfo_path:str):
    topo_sort_str = []
    for item in topo_order:
        if isinstance(item, tuple):
            topo_sort_str.append(" <-> ".join(item))
        else:
            topo_sort_str.append(item)

    call_graph_str = []
    for caller, callees in call_graph.items():
        if callees:  # If there are callees
            if isinstance(callees, list):
                call_graph_str.append(f"{caller} -> {', '.join(callees)}")
            else:
                call_graph_str.append(f"{caller} -> {callees}")
        else:  # If no callees
            call_graph_str.append(f"{caller}")
               
    with open(output_projectInfo_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(project_tree) + "\n\nSPLIT_TAG\n\n" + 
                "\n".join(call_graph_str) + "\n\nSPLIT_TAG\n\n" + 
                "\n".join(topo_sort_str))


def start_cons(args):
    root_dir = args.root_dir
    project_name = args.source_project_name
    source_project_path = args.source_project_path
    parsed_project_path = args.parsed_project_path
        



    # Step1: expand macro
    expanded_dealed_dir = process_macro_expansion(source_project_path)
    logger.info(f"Successfully processed macros. Output directory: {expanded_dealed_dir}")
    
    # Step2: doxygen generate Info
    entities_path, relationships_path = extract_doxygen_info(str(expanded_dealed_dir), parsed_project_path)
    projectInfo_path = os.path.join(parsed_project_path, f"{project_name}_ProjectInfo.txt")
    if os.path.exists(projectInfo_path):
        logger.info(f"Reusing existing project info file: {projectInfo_path}")
        return entities_path, relationships_path, projectInfo_path
    
    # # obtain the translation info
    # ## obtain the project tree
    pathList = []
    pathList.append(project_name)
    obtain_project_tree(pathList, expanded_dealed_dir)

    h_file_set = set()
    with open(entities_path, 'r', encoding='utf-8') as f:
        entities_list = json.load(f)
    for entity in entities_list:
        if "LOCAL:" in entity['is_system']:
            h_file = os.path.basename(entity['is_system'].split(":")[1].strip().strip("]"))
            if h_file.endswith(".h"):
                h_file_set.add(h_file)
    h_file_set = "H_FILE_LIST\n" + "\n".join(h_file_set)
    pathList.append(h_file_set)
    
    ## topological_sort_call_graph
    call_graph = extract_call_graph(entities_path, relationships_path)
    topo_order = topological_sort_call_graph(call_graph)
    if not os.path.exists(projectInfo_path): write_projectInfo(pathList, call_graph, topo_order, projectInfo_path)
    ## write the project tree and topo_order to the ProjectInfo.txt
    # write_projectInfo(pathList, call_graph, topo_order, projectInfo_path)
    return entities_path, relationships_path, projectInfo_path

                 
def main_test():
    root_dir = "../Code_Package"

    dir_name = "Code_Package/dataset/crown_dataset" 
    project_names = os.listdir(dir_name)
    project_name_list = [os.path.join("crown_dataset", project_name) for project_name in project_names]
    
    for project_name in project_name_list:
        if "_expanded" in project_name: continue
        
        print(project_name)
        source_project_path = os.path.join(root_dir, f"dataset/{project_name}") 
        parsed_project_path = os.path.join(root_dir, f"dataset/parsed_projects")


        # Step1: expand macro
        expanded_dealed_dir = process_macro_expansion(source_project_path)
        logger.info(f"Successfully processed macros. Output directory: {expanded_dealed_dir}")
        
        # Step2: doxygen generate Info
        entities_path, relationships_path = extract_doxygen_info(str(expanded_dealed_dir), parsed_project_path)
        
        # # # # obtain the translation info
        # # # ## obtain the project tree
        pathList = []
        pathList.append(os.path.basename(project_name))
        obtain_project_tree(pathList, expanded_dealed_dir)
        
        
        h_file_set = set()
        with open(entities_path, 'r', encoding='utf-8') as f:
            entities_list = json.load(f)
        for entity in entities_list:
            if "LOCAL:" in entity['is_system']:
                h_file = os.path.basename(entity['is_system'].split(":")[1].strip().strip("]"))
                if h_file.endswith(".h"):
                    h_file_set.add(h_file)
        h_file_set = "H_FILE_LIST\n" + "\n".join(h_file_set)
        pathList.append(h_file_set)
                
        # # ## topological_sort_call_graph
        call_graph = extract_call_graph(entities_path, relationships_path)
        topo_order = topological_sort_call_graph(call_graph)
        projectInfo_path = os.path.join(parsed_project_path, f"{os.path.basename(project_name)}_ProjectInfo.txt")
        ## write the project tree and topo_order to the ProjectInfo.txt
        write_projectInfo(pathList, call_graph, topo_order, projectInfo_path)
       
              
if __name__ == "__main__":
    
    main_test()
