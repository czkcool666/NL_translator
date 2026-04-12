from tqdm import tqdm
from tree_sitter import Language, Parser
from monitors4codegen.multilspy import SyncLanguageServer
from monitors4codegen.multilspy.multilspy_config import MultilspyConfig
from monitors4codegen.multilspy.multilspy_logger import MultilspyLogger
import os
from collections import defaultdict, deque
import json
import argparse
import glob

elementTypes = ['preproc_include','macro_definition','typedef_definition', 'struct_definition',
                  'enum_definition', 'globalVar_definition', 'staticVar_definition','function_definition', 'preproc_if']

excluded_macros = ["__cplusplus", 
                   "__STDC__", 
                   "__GNUC__", "__GNUC_MINOR__", "__GNUC_PATCHLEVEL__", "__VERSION__", # 版本号相关
                   "__STDC__","__STDC_NO_ATOMICS__", "__STDC_NO_COMPLEX__","__STDC_NO_THREADS__" 
                   ]


# obtain the Trans Unit. Each Unit contain the relevant dependency (e.g, called method, used struct/enum/global variabl, etc.)
class Slicer:
    def __init__(self, args):
        self.args = args
        
        # === initial input path and output path === #
        self.source_project_path = self.args.source_project_path
        self._output_callGraph_path = os.path.join(self.args.parsed_project_path ,self.args.source_project_name+"_callGraph.jsonl")
        self._output_projectInfo_path = os.path.join(self.args.parsed_project_path ,self.args.source_project_name+"_projectInfo.txt")

        # ====  initial treesitter parser ==== #
        PARSER_LOCATION = os.path.join(self.args.root_path, f"dependencyLib/{self.args.source_lang}_parser.so")
        LANGUAGE = Language(PARSER_LOCATION, self.args.source_lang)
        self.parser = Parser()
        self.parser.set_language(LANGUAGE)
        
        # ==== initial lsp ==== #
        config = MultilspyConfig.from_dict({"code_language": f"{self.args.source_lang}"}) # Also supports "python", "rust", "csharp"
        logger = MultilspyLogger()
        self.lsp = SyncLanguageServer.create(config, logger, self.source_project_path)
    
    def main_parser(self):
        # Determine whether to re-parser the project
        re_parser_tag = self.is_file_non_empty(self._output_callGraph_path, self._output_projectInfo_path)
        if not re_parser_tag:
            self._repo_parser()
        
        call_graph_dict = self.build_call_graph(self._output_callGraph_path)
        topo_sort_result_list = self.topological_sort_call_graph(call_graph_dict)
        self.append_topo_sort_to_project_info(topo_sort_result_list, call_graph_dict)
        
        return self._output_callGraph_path, self._output_projectInfo_path
        
        
    def _repo_parser(self):        
        functional_code_files = self.fileClassfication()
        with self.lsp.start_server():
            code_elements_list = []
            for path in tqdm(functional_code_files):
                print("deal:", os.path.basename(path))
                with open(os.path.join(self.source_project_path, path), 'r', encoding='utf-8') as f:
                    self.path_code_content = f.read()
                
                tree = self.parser.parse(bytes(self.path_code_content, 'utf8'))
                root_node = tree.root_node
                parsedCode_list = self.traverse_root_node(root_node, path)
                code_elements_list.extend(parsedCode_list)
                                        
            # replace header to implemenataion
            self.replace_h_with_imple(code_elements_list)
        
    def traverse_root_node(self, root_node, path):
        parsedCode_list = []
        
        def process_node(current_node, condition_code=""):
            
            if current_node.type in ['comment']: return
            parsedCode_dict = {}
            
            if current_node.type in ['preproc_ifdef','preproc_elif', 'preproc_if', 'preproc_else']:
                # Get the first child node (condition node)
                first_child_node = current_node.children[1]
                
                # Get start and end line
                start_line = first_child_node.start_point[0]
                end_line = first_child_node.end_point[0]
                
                # Get the code cont for the condition
                new_condition_code = "\n".join(self.path_code_content.split("\n")[start_line:end_line+1])
                 
                for child in current_node.children:
                    process_node(child, new_condition_code)
                return
                     
            if current_node.type in ['function_definition']:
                parsedCode_dict['type'] = "function_definition"
                # code_cont = current_node.text.decode("utf8") # function_code  
                _, identifier_text = self.has_function_declarator(current_node)
                                
                if path.endswith(".h"):
                    parsedCode_dict['calling_code'] = ""
                else:
                    called_identifiers = self.deep_traverse_node(current_node, path)
                    filtered_identifier = []
                    for iden in called_identifiers:
                        if not (path in iden and int(iden.split("#")[2])>=current_node.start_point[0] 
                                and int(iden.split("#")[2])<=current_node.end_point[0]):
                            filtered_identifier.append(iden)
                    parsedCode_dict['calling_code'] = "\n".join(filtered_identifier)


            elif current_node.type in ["preproc_def", "preproc_function_def", "preproc_call"]: 
                parsedCode_dict['type'] = "macro_definition"
                parsedCode_dict['calling_code'] = ""
                # code_cont = current_node.text.decode("utf8")  # macro_code
                identifier_text = ""
                for _child_node in current_node.children:
                    if _child_node.type in ['preproc_arg', 'identifier']:
                        identifier_text = _child_node.text.decode('utf8')
                        break
            elif current_node.type in ['type_definition']:
                parsedCode_dict['type'] = "typedef_definition"
                parsedCode_dict['calling_code'] = ""
                # code_cont = current_node.text.decode("utf8") # typedef_code

                called_identifiers = self.deep_traverse_node(current_node, path)
                filtered_identifier = []
                for iden in called_identifiers:
                    if not (path in iden and int(iden.split("#")[2])>=current_node.start_point[0] 
                            and int(iden.split("#")[2])<=current_node.end_point[0]):
                        filtered_identifier.append(iden)
                parsedCode_dict['calling_code'] = "\n".join(filtered_identifier)
                
                identifier_text = ""
                for _child_node in current_node.children:
                    if _child_node.type in ['type_identifier']:
                        identifier_text = _child_node.text.decode('utf8')
                        break
                    
            elif current_node.type in ['struct_specifier','enum_specifier']: # deal 'struct' and 'enum'
                parsedCode_dict['type'] = "struct_definition" if current_node.type in ['struct_specifier'] else "enum_definition"
                called_identifiers = self.deep_traverse_node(current_node, path)
                filtered_identifier = []
                for iden in called_identifiers:
                    if not (path in iden and int(iden.split("#")[2])>=current_node.start_point[0] 
                            and int(iden.split("#")[2])<=current_node.end_point[0]):
                        filtered_identifier.append(iden)
                parsedCode_dict['calling_code'] = "\n".join(filtered_identifier)
                
                identifier_text = ""
                for _child_node in current_node.children:
                    if _child_node.type in ['type_identifier']:
                        identifier_text = _child_node.text.decode('utf8')
                        break
                    
            elif current_node.type in ['declaration']: 
                                
                # Check if this is a function declaration
                is_function, _identifier_text = self.has_function_declarator(current_node)
                if is_function:
                    if path.endswith(".c"): return
                    parsedCode_dict['type'] = "function_declaration"
                    identifier_text = _identifier_text
                else:
                    parsedCode_dict['type'] = "var_declaration"
                    identifier_text = self.find_first_identifier(current_node)

                        
                parsedCode_dict['calling_code'] = ""

                
            elif current_node.type not in ['comment']:
                parsedCode_dict['type'] = "other"
                parsedCode_dict['calling_code'] = ""
                identifier_text = self.find_first_identifier(current_node)
                
            parsedCode_dict['code_id'] = f"{path}#{identifier_text}"
            parsedCode_dict['start_line'] = current_node.start_point[0]
            parsedCode_dict['end_line'] = current_node.end_point[0]
            
            start_line = current_node.start_point[0]
            end_line = current_node.end_point[0]
            code_cont = "\n".join(self.path_code_content.split("\n")[start_line:end_line+1])
            parsedCode_dict["code_cont"] = code_cont

            parsedCode_dict['condition_code'] = condition_code
            
            parsedCode_list.append(parsedCode_dict)
        
        for root_child_node in root_node.children:
            process_node(root_child_node)
        
        return parsedCode_list

    
    def deep_traverse_node(self, child_node, path):
        identifiers = []
        def traverse(current_node):
            if 'identifier' in current_node.type:
                # obtain the 'identifier' content
                identifier_text = current_node.text.decode("utf8")
                try:
                    definitions = self.lsp.request_definition(
                        path,
                        current_node.start_point[0],  
                        current_node.start_point[1], 
                    )
                    identifier_with_def = f"{definitions[0]['relativePath']}#{identifier_text}#{definitions[0]['range']['end']['line']}"
                    if identifier_with_def not in identifiers:
                        identifiers.append(identifier_with_def)
                except Exception as e:
                    print(f"Error getting definition for {identifier_text}: {e}")
            
            for child in current_node.children:
                traverse(child)
        traverse(child_node)
        
        return identifiers


    def find_first_identifier(self, node):
        if node.type == 'identifier':
            return node.text.decode('utf8')
        for child in node.children:
            result = self.find_first_identifier(child)
            if result:
                return result
        return ""
                    
    def has_function_declarator(self, node):
        if node.type == 'function_declarator':
            # Find identifier in children
            for child in node.children:
                if child.type == 'identifier':
                    return True, child.text.decode('utf8')
            return True, ""  # Function declarator found but no identifier
        for child in node.children:
            result, identifier = self.has_function_declarator(child)
            if result:
                return True, identifier
        return False, ""


    def build_call_graph(self, callGraph_path):
        """
        Output format: {caller_id: [callee_id1, callee_id2, ...]}
        """
        call_graph = defaultdict(list)
        parsed_codes_list = []
        with open(callGraph_path, 'r', encoding='utf-8') as f:
            parsed_codes_list = [json.loads(line) for line in f]
        all_code_id = [ele['code_id'] for ele in parsed_codes_list]
        for parsed_code in parsed_codes_list:
            caller_id = parsed_code['code_id']
            if caller_id.strip().endswith("#"): continue
            if 'calling_code' in parsed_code and parsed_code['calling_code']:
                called_codes = parsed_code['calling_code'].split('\n')
                for called_code in called_codes:
                    parts = called_code.split('#')
                    if len(parts) >= 2:
                        callee_id = '#'.join(parts[0:2])
                        if callee_id in all_code_id and callee_id != caller_id:
                            call_graph[caller_id].append(callee_id)
            elif parsed_code['code_id'].split("#")[0].strip().endswith(".c") and parsed_code['type']!='function_declaration':
                call_graph[caller_id] = ""
        self.draw_dot_png(call_graph)
        return dict(call_graph)

    
    def draw_dot_png(self, call_graph):
        dot_path = self._output_callGraph_path.replace('_callGraph.jsonl', '_callGraph.dot')
        with open(dot_path, 'w', encoding='utf-8') as f:
            f.write('digraph CallGraph {\n')
            f.write('    rankdir=LR;\n')  
            f.write('    node [shape=box, style=filled, fillcolor=lightblue];\n')
            
            nodes = set()
            for caller, callees in call_graph.items():
                if caller not in nodes:
                    caller_parts = caller.split('#')
                    if len(caller_parts) == 2:
                        label = f"{os.path.basename(caller_parts[0])}\\n{caller_parts[1]}"
                    else:
                        label = caller
                    f.write(f'    "{caller}" [label="{label}"];\n')
                    nodes.add(caller)
                
                for callee in callees:
                    if callee not in nodes:
                        callee_parts = callee.split('#')
                        if len(callee_parts) == 2:
                            label = f"{os.path.basename(callee_parts[0])}\\n{callee_parts[1]}"
                        else:
                            label = callee
                        f.write(f'    "{callee}" [label="{label}"];\n')
                        nodes.add(callee)
                    f.write(f'    "{caller}" -> "{callee}";\n')
                    
            f.write('}\n')
        
    
    def replace_h_with_imple(self,code_elements):
        # Read all code elements
        
        header_to_impl = {}
        
        header_declarations = {}
        for elem in code_elements:
            code_id = elem['code_id']
            if code_id.split('#')[0].endswith('.h') and elem.get('type') == 'function_declaration':
                file_path = code_id.split('#')[0]
                func_name = code_id.split('#')[1]
                # Store using both file path and function name
                header_key = (file_path, func_name)
                header_declarations[header_key] = code_id

        # Match implementations with header declarations
        for elem in code_elements:
            code_id = elem['code_id']
            if code_id.split('#')[0].endswith('.c') and elem.get('type') == 'function_definition':
                impl_file_path = code_id.split('#')[0]
                func_name = code_id.split('#')[1]
                
                # Try to find a matching header file (convert .c to .h)
                header_file_path = impl_file_path.replace('.c', '.h')
                header_key = (header_file_path, func_name)
                
                # If exact match exists, use it
                if header_key in header_declarations:
                    header_id = header_declarations[header_key]
                    header_to_impl[header_id] = f"{code_id}#{elem.get('start_line', '')}"
                else:
                    # Fall back to function name only if needed
                    for (h_path, h_func), h_id in header_declarations.items():
                        if h_func == func_name:
                            header_to_impl[h_id] = f"{code_id}#{elem.get('start_line', '')}"
                            break

        # Update calling_code references
        for elem in code_elements:
            if 'calling_code' in elem and elem['calling_code']:
                called_codes = elem['calling_code'].split('\n')
                updated_calls = []
                for called_code in called_codes:
                    parts = called_code.split('#')
                    if len(parts) >= 2:
                        # Reconstruct the callee_id (without line number)
                        callee_id = '#'.join(parts[0:2])
                        
                        # If this is a header declaration with an implementation, replace it
                        if callee_id in header_to_impl:
                            updated_calls.append(header_to_impl[callee_id])
                        else:
                            updated_calls.append(called_code)
                    else:
                        updated_calls.append(called_code)
                elem['calling_code'] = '\n'.join(updated_calls)

        with open(self._output_callGraph_path, 'w', encoding='utf-8') as f:
            for elem in code_elements:
                f.write(json.dumps(elem) + '\n')
    
    def find_cycles(self, call_graph):
        def dfs(node, path):
            if node in path:
                cycle = path[path.index(node):]
                print(f"Found cycle: {' -> '.join(cycle)} -> {node}")
                return True
            
            path.append(node)
            if node in call_graph and isinstance(call_graph[node], list):
                for neighbor in call_graph[node]:
                    if dfs(neighbor, path):
                        return True
            path.pop()
            return False

        visited = set()
        for node in call_graph:
            if node not in visited:
                dfs(node, [])

    def topological_sort_call_graph(self, call_graph):
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

    def GetIndent(self, s):
        return len(s) - len(s.lstrip(' '))

    # obtain the project tree and make a classification
    def fileClassfication(self):
        if not os.path.exists(self._output_projectInfo_path):
            pathList = []
            pathList.append(f"{os.path.basename(self.source_project_path)}")
            self.obtain_project_tree(pathList, self.source_project_path)
            
            allFilePaths =  [os.path.join(root, file) for root, _, files in os.walk(self.source_project_path) for file in files]
            functional_code_files = [file.replace(self.source_project_path+"/","") for file in allFilePaths if (file.endswith(".c") or file.endswith(".h")) and "test" not in file]
            
            pathCont = "\n".join(pathList) + "\n\nFILE_SPLIT\n\n" + "\n".join(functional_code_files)
            with open(self._output_projectInfo_path, 'w', encoding='utf-8') as f:
                f.write(pathCont)
             
        else:
            with open(self._output_projectInfo_path, 'r', encoding='utf-8') as f:
                pathCont = f.read()
            functional_code_files = pathCont.split("\n\nFILE_SPLIT\n\n")[1].split("\n")
        return functional_code_files
   
    def obtain_project_tree(self, pathList, root_path, indent=""):
        
        if not os.path.exists(root_path):
            print(f"Path Not Exist: {root_path}")
            return

        entries = [e for e in os.listdir(root_path) if not e.startswith('.')]  # Filter out dot files/directories
        entries.sort()  

        for index, entry in enumerate(entries):
            full_path = os.path.join(root_path, entry)
            is_last = index == len(entries) - 1  
            
            if is_last:
                pathList.append(f"{indent}└── {entry}")
                new_indent = indent + "    " 
            else:
                pathList.append(f"{indent}├── {entry}")
                new_indent = indent + "│   "  

            if os.path.isdir(full_path):
                self.obtain_project_tree(pathList, full_path, new_indent)

    def is_file_non_empty(self, path1, path2, TAG=False):
        if TAG:
            if os.path.exists(path1) and os.path.isfile(path1):
                os.remove(path1)
            if os.path.exists(path2) and os.path.isfile(path2):
                os.remove(path2)
        if not os.path.isfile(path1) or not os.path.isfile(path2):
            return False
        if os.path.getsize(path1) == 0 or os.path.getsize(path2) == 0:
            return False
        return True

    def append_topo_sort_to_project_info(self, topo_sort_result_list, call_graph_dict):
        # Convert call graph dict to string format
        call_graph_str = []
        for caller, callees in call_graph_dict.items():
            if callees:  # If there are callees
                if isinstance(callees, list):
                    call_graph_str.append(f"{caller} -> {', '.join(callees)}")
                else:
                    call_graph_str.append(f"{caller} -> {callees}")
            else:  # If no callees
                call_graph_str.append(f"{caller}")

        # Convert topological sort results to string format
        topo_sort_str = []
        for item in topo_sort_result_list:
            if isinstance(item, tuple):
                topo_sort_str.append(" <-> ".join(item))
            else:
                topo_sort_str.append(item)
        
        # Read the existing content
        with open(self._output_projectInfo_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()
        
        # Prepare new content with both call graph and topo sort
        parts = existing_content.split("\n\nFILE_SPLIT\n\n")
        if len(parts) >= 2:  # Has at least project tree and file list
            new_content = (parts[0] + "\n\nFILE_SPLIT\n\n" + 
                        parts[1] + "\n\nFILE_SPLIT\n\n" + 
                        "\n".join(call_graph_str) + "\n\nFILE_SPLIT\n\n" +
                        "\n".join(topo_sort_str))
        else:
            new_content = (existing_content + "\n\nFILE_SPLIT\n\n" + 
                         "\n".join(call_graph_str) + "\n\nFILE_SPLIT\n\n" + 
                         "\n".join(topo_sort_str))
        
        # Write the updated content back to the file
        with open(self._output_projectInfo_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--source_lang', type=str, default="c")
    parser.add_argument('--root_path', type=str, default="../Code_Package")
    parser.add_argument('--source_project_name', type=str, default="quadtree_0_1_0") # quadtree-0.1.0, avl
    parser.add_argument("--source_project_path", default=None, type=str, help="source project path")
    
    args = parser.parse_args()
    args.source_project_path = os.path.join(args.root_path, "dataset", args.source_project_name)
    args.parsed_project_path = os.path.join(args.root_path, "dataset/parsed_projects")
    repo_parser = Slicer(args)
    path1, path2 = repo_parser.main_parser()