import os
import sys
from webbrowser import Elinks
from tree_sitter import Language, Parser
import argparse
from tqdm import tqdm
from datetime import datetime
from collections import defaultdict, deque
import subprocess
import json
import logging
import subprocess
import time
import re
import copy
import traceback
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None
import KG_construction as kg_construction
import handcraftPrompt
from generator import Generator
from translator import Translator
from utils.rust_parser import RustParser
from utils.c_parser import CParser
from utils.git_manage import GitManager

current_dir = os.getcwd()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(message)s', datefmt='%m/%d/%Y %H:%M:%S', level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Main:
    def __init__(self, args):
        self.args = args
        self.Max_fixCount = 5
        
        self.rust_parser = RustParser(self.args.root_dir)
        self.c_parser = CParser(self.args.root_dir)
        self.git_manager = GitManager()
        # initial generator
        self.generator = Generator(args)
        self.translator = Translator(args, self.generator)

    def translation_setup(self):
        os.makedirs(self.args.trans_project_path, exist_ok=True)
        if "LLM_only" in self.args.translate_mode:
            trans_metadata_path = os.path.join(self.args.trans_project_path, self.args.source_project_name + "_LLM_only_trans_metadata.jsonl")
        elif "Trans_PA" in self.args.translate_mode:
            trans_metadata_path = os.path.join(self.args.trans_project_path, self.args.source_project_name + "_Trans_PA_trans_metadata.jsonl")
        elif "Trans_not_RA" in self.args.translate_mode:
            trans_metadata_path = os.path.join(self.args.trans_project_path, self.args.source_project_name + "_Trans_not_RA_trans_metadata.jsonl")
        elif "Trans_not_PU" in self.args.translate_mode:
            trans_metadata_path = os.path.join(self.args.trans_project_path, self.args.source_project_name + "_Trans_not_PU_trans_metadata.jsonl")
        else:
            logger.error(f"Invalid translation mode: {self.args.translate_mode}")
            exit(1)
        

        entities_path, relationships_path, projectInfo_path = kg_construction.start_cons(self.args)
        with open(projectInfo_path, 'r', encoding='utf-8') as f:
            c_project_info = f.read()
        c_project_tree, _ ,c_topo_sort_str =c_project_info.split("\n\nSPLIT_TAG\n\n")
        

        self.rust_project_path = os.path.join(self.args.trans_project_path, self.args.source_project_name)
        if not os.path.exists(self.rust_project_path) or not os.path.exists(trans_metadata_path):
            rust_pj_tree_str, file_map_str = self.translator._pj_tree_trans(c_project_tree)
            if not os.path.exists(self.rust_project_path):
                new_rust_pj_tree_str = self.create_project_structure(rust_pj_tree_str, self.args.trans_project_path)
            else:
                pathList = [self.args.source_project_name]
                self.obtain_project_tree(pathList, self.rust_project_path)
                new_rust_pj_tree_str = "\n".join(pathList)
            print(new_rust_pj_tree_str)
            

            file_map_list = []
            for line in file_map_str.split('\n'):
                line = line.strip()
                if '->' in line:
                    source, target = map(str.strip, line.split('->'))
                    file_map_list.append({"source": source.replace(self.args.source_project_name+"/", ""), "target": target.replace(self.args.source_project_name+"/", ""), "map_tag": "file"})
            

            file_map_list.append({"source": c_project_tree, "target": new_rust_pj_tree_str, "map_tag": "project_tree"})
            with open(trans_metadata_path, 'w', encoding='utf-8') as f:
                for item in file_map_list:
                    json.dump(item, f, ensure_ascii=False)
                    f.write('\n')
        self.ensure_valid_cargo_toml()
        verf_Result = self.rust_compile_verfication()
        if verf_Result != "Success":
            logger.error(f"Rust pro verification failed: {verf_Result}")
            exit(1)
        return trans_metadata_path, entities_path, relationships_path, c_topo_sort_str

    def ensure_valid_cargo_toml(self):
        os.makedirs(self.rust_project_path, exist_ok=True)
        cargo_toml_path = os.path.join(self.rust_project_path, 'Cargo.toml')
        should_write = not os.path.exists(cargo_toml_path)
        if not should_write and tomllib is not None:
            try:
                with open(cargo_toml_path, 'rb') as f:
                    tomllib.load(f)
            except Exception:
                should_write = True
        if should_write:
            with open(cargo_toml_path, 'w') as f:
                f.write(f'''[package]
name = "{self.args.source_project_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
''')
        self.normalize_rust_project_skeleton(self.rust_project_path)

    def normalize_rust_project_skeleton(self, project_path):
        src_dir = os.path.join(project_path, 'src')
        if not os.path.isdir(src_dir):
            return

        main_rs_path = os.path.join(src_dir, 'main.rs')
        if os.path.exists(main_rs_path):
            with open(main_rs_path, 'r', encoding='utf-8') as f:
                main_content = f.read()
            if not main_content.strip():
                with open(main_rs_path, 'w', encoding='utf-8') as f:
                    f.write('fn main() {}\n')

        common_dir = os.path.join(src_dir, 'common')
        if os.path.isdir(common_dir):
            common_rs_files = [
                f.replace('.rs', '')
                for f in os.listdir(common_dir)
                if f.endswith('.rs') and f != 'mod.rs'
            ]
            mod_rs_path = os.path.join(common_dir, 'mod.rs')
            with open(mod_rs_path, 'w', encoding='utf-8') as f:
                for common_rs in common_rs_files:
                    f.write(f"pub mod {common_rs};\n")

        src_lib_path = os.path.join(src_dir, 'lib.rs')
        src_rs_files = [
            f.replace('.rs', '')
            for f in os.listdir(src_dir)
            if f.endswith('.rs') and f not in {'lib.rs', 'main.rs'}
        ]
        with open(src_lib_path, 'w', encoding='utf-8') as f:
            for src_rs in src_rs_files:
                f.write(f"pub mod {src_rs};\n")
            if os.path.isdir(common_dir):
                f.write("pub mod common;\n")
            for src_rs in src_rs_files:
                f.write(f"pub use crate::{src_rs}::*;\n")
            if os.path.isdir(common_dir):
                for common_rs in common_rs_files:
                    f.write(f"pub use crate::common::{common_rs}::*;\n")

        
    def trans_LLM_only(self):  
        trans_metadata_path, entities_path, relationships_path, c_topo_sort_str = self.translation_setup();
        

        with open(trans_metadata_path, 'r', encoding='utf-8') as f:
            trans_metadata = [json.loads(line.strip()) for line in f.readlines()]


        freeFunction_list = []
        for meta in trans_metadata:
            if "trans_rust_code" in meta and meta['trans_rust_code'] == "Free_Function":
                free_function_name = [source_c_code_id.split("#")[0] for source_c_code_id in meta['source_c_code_id']]
                freeFunction_list.extend(free_function_name)
                

        call_graph_list = self.call_graph_load(relationships_path, entities_path)
        func_SA_json_path, struct_SA_json_path = self.SA_result_path()
        
        

        def code_trans(code_unique_names):
            nonlocal trans_metadata
            source_called_name = []
            all_source_code_list = []
            var_typedef_TAG = False
            for code_unique_name in code_unique_names:
                source_code_type = call_graph_list[code_unique_name]["source_type"]
                source_code = call_graph_list[code_unique_name]["source_code"].strip()
                if (source_code_type == "variable" and not self.is_large_array(source_code)) or \
                (source_code_type == "typedef" and len(source_code.split("\n"))==1):
                    continue 

                called_name_list = call_graph_list[code_unique_name]["source_called_name"]
                source_called_name.extend(called_name_list) 

                called_var_typedef = ""
                for called_name in called_name_list:
                    called_code_type = call_graph_list[called_name]["source_type"]
                    if called_code_type == "variable" and not self.is_large_array(call_graph_list[called_name]["source_code"].strip()):
                        called_source_code = call_graph_list[called_name]["source_code"].strip() + " // [NOTE: MAKE THIS VARIABLE TO LOCAL!]"
                        var_typedef_TAG = True
                        source_called_name.extend(call_graph_list[called_name]["source_called_name"]) # 将这个变量名调用的对象，也添加进去
                    elif called_code_type == "typedef" and len(call_graph_list[called_name]["source_code"].strip().split("\n"))==1:
                        called_source_code = call_graph_list[called_name]["source_code"].strip() + " // [NOTE: REPLACE THIS IN USAGE!]"
                        var_typedef_TAG = True
                        source_called_name.extend(call_graph_list[called_name]["source_called_name"])
                    else: called_source_code = ""
                    called_var_typedef = called_var_typedef + "\n" + called_source_code
                all_source_code_list.append(call_graph_list[code_unique_name]["source_code"].strip())
            
            if len(all_source_code_list)==0: return   
            source_c_code = "\n---\n".join(all_source_code_list)
            
            
            trans_rust_paths = [meta for meta in trans_metadata if meta['map_tag'] == "file" and meta['source'] == code_unique_names[0].split("#")[1]]
            assert len(trans_rust_paths) == 1, f"Error: No corresponding Rust code path found for {code_unique_names}"
            trans_rust_path = trans_rust_paths[0]['target'] 

            rust_depend_metas_dict = {}
            for called_unique_name in source_called_name:
                rust_depend_meta = [meta for meta in trans_metadata if meta['map_tag'] == "code" and called_unique_name in meta['source_c_code_id']]
                for meta in rust_depend_meta:

                    meta_key = (tuple(meta['source_c_code_id']), meta['trans_rust_path'])
                    rust_depend_metas_dict[meta_key] = meta

            rust_depend_metas = list(rust_depend_metas_dict.values())
            

            source_c_code_info = (call_graph_list, source_c_code, source_code_type)
            SA_result = ""
            
            trans_rust_code, toml_depend, trans_rust_code_context = "","",""
            verf_Result = "Success"
            
            token_count = self.generator.get_token_count(source_c_code)
            truncate_tag = False
            if token_count and token_count > 10000:
                half_length = 5000
                truncate_tag = True
                truncate_pos = source_c_code.rfind('\n', 0, half_length)
                if truncate_pos == -1: truncate_pos = half_length
                trun_source_c_code = source_c_code[:truncate_pos] + "\n// ... [TOO LONG] ..."
                if source_c_code.strip().endswith("}"):source_c_code = trun_source_c_code + "\n}"
                else: source_c_code = trun_source_c_code
                
            judged_source_c_code = ""
            # DEBUG
            if source_code_type == "function":
                called_code_context = ""
                for called_unique_name in source_called_name:
                    called_code_context = called_code_context + "\n------\n" + call_graph_list[called_unique_name]["source_code"]
                pointToInfo = ""
                for SA in SA_result.split("\n"):
                    if "pointTo" in SA: 
                        pointToInfo = pointToInfo + "\n" + SA
                
                freeAted_source_c_code = self.free_annotation(source_c_code, freeFunction_list)
                judged_source_c_code = self.translator._free_judge(freeAted_source_c_code, called_code_context, pointToInfo)
            
            if judged_source_c_code == "Free_Function":
                free_function_name = [source_c_code_id.split("#")[0] for source_c_code_id in code_unique_names]
                freeFunction_list.extend(free_function_name)
                trans_metadata.append({"trans_rust_code_context": "", "rust_definition_name": "","map_tag": "code", "Verfi_Tag": "Free_Function",
                                        "trans_rust_code": "Free_Function", "source_code_type":source_code_type,
                                        "source_c_code_id": code_unique_names, "trans_rust_path": trans_rust_path})

            else:
                to_trans_c_code = judged_source_c_code if judged_source_c_code != "" else source_c_code
                to_trans_c_code = called_var_typedef.strip() + "\n" + to_trans_c_code.strip()
                rust_code_path = os.path.join(self.args.trans_project_path, self.args.source_project_name, trans_rust_path)
                with open(rust_code_path, 'r', encoding='utf-8') as f:
                    rust_file_code = f.read()            
                
                trans_rust_code_temp, toml_depend = \
                    self.translator._code_trans(to_trans_c_code, rust_depend_metas, code_unique_names, rust_file_code.strip(), SA_result, var_typedef_TAG)

                trans_rust_code = self.remove_duplicate_trans(trans_rust_code_temp, trans_metadata)
                trans_rust_code_context = self.rust_parser.extract_item_content(trans_rust_code)
                if len(trans_rust_code_context) == 0: trans_rust_code_context  = trans_rust_code
            
                self.git_manager.ensure_git_repo(self.rust_project_path)
                initial_commit = self.git_manager.git_save_state(self.rust_project_path, f"Initial translation for {code_unique_names}")
                
                written_rust =  self.trans_rust_code_write(trans_rust_code,trans_rust_path, "")
                self.toml_write(toml_depend)

                trans_metadata.append({"source_c_code_id": code_unique_names, "map_tag": "code", "source_code_type":source_code_type,
                                       "trans_rust_path": trans_rust_path, "trans_rust_code_context": trans_rust_code_context,
                                       "trans_rust_code": written_rust[0],
                                       "rust_definition_name": self.rust_parser.get_rust_definitions(trans_rust_code)
                                       })
            
                verf_Result = self.rust_compile_verfication()
                original_trans_metadata = copy.deepcopy(trans_metadata)                
                fixedError = [] 
                error_count = 0
                compilation_success = False  
                

                try:
                    while verf_Result != "Success":
                        error_count = error_count + 1
                        if error_count > self.Max_fixCount or truncate_tag:
                            logger.warning(f"Reach the maximum number of attempts ({self.Max_fixCount}), exit the repair loop")
                            break
                        
                        fixedError.append(verf_Result)
                        
                        error_log = verf_Result['error_log']
                        primary_item = verf_Result['primary_item']

                        fix_rust_code_context = "\n==========\n".join([meta['trans_rust_code'].strip() for meta in rust_depend_metas])

                        cycle_metas = [meta for meta in trans_metadata if "trans_rust_code" in meta and primary_item.strip() in meta['trans_rust_code']]
                        if len(cycle_metas)!=0 and len(cycle_metas[0]['rust_definition_name'])>1: 
                            ex_context = cycle_metas[0]['trans_rust_code'].replace(primary_item.strip(), "")
                            fix_rust_code_context = ex_context + "\n==========\n" + fix_rust_code_context
                        
                        related_item = self.translator._error_related_code(error_log, primary_item, fix_rust_code_context)
                        rust_item = primary_item+"\n"+related_item
                        if "cannot find " in error_log:
                            fix_SA_info = self.extract_fileInfo(rust_item, trans_metadata)
                        else:
                            fix_SA_info = self.extract_SA4Error(rust_item, trans_metadata, call_graph_list, func_SA_json_path, struct_SA_json_path)
                        fixed_rust_list,toml_de = self.translator._rust_error_fix(error_log, primary_item, related_item, fix_SA_info)
                        if len(toml_de)!=0: self.toml_write(toml_de)
                        trans_metadata = self.replaceItem_fixed_rust(fixed_rust_list, trans_metadata, verf_Result)

                        fix_commit = self.git_manager.git_save_state(
                            self.rust_project_path, 
                            f"Fix attempt {len(fixedError)} for {code_unique_names}"
                        )
                        
                        verf_Result = self.rust_compile_verfication()
                    
                    if verf_Result == "Success":
                        compilation_success = True

                except Exception as e:
                    logger.error(f"Exception stack trace:\n{traceback.format_exc()}")
    
                if not compilation_success:
                    trans_metadata = self._handle_translation_failure(
                        trans_metadata, original_trans_metadata, initial_commit,
                        to_trans_c_code, source_code_type, rust_depend_metas,
                        code_unique_names, rust_file_code.strip(), SA_result,
                        trans_rust_path, verf_Result, written_rust
                    )
    

                if len(fixedError) == 0: verfi_tag = "No_Fix_Compile_Success"
                elif verf_Result == "Success": verfi_tag = f"Fixed_{len(fixedError)}_Compile_Success"
                else: verfi_tag = f"Fixed_{len(fixedError)}_Compile_Failed"
                if truncate_tag: verfi_tag = "Fixed_truncate_Compile_Failed"
                
                trans_metadata[-1]["Verfi_Tag"] = verfi_tag
                                
            with open(trans_metadata_path, 'a', encoding='utf-8') as f:
                json.dump(trans_metadata[-1], f, ensure_ascii=False)
                f.write('\n')
                
        for code_id_entry in tqdm(c_topo_sort_str.split("\n"), desc="Processing code_ids"):
            code_unique_names = [id.strip() for id in code_id_entry.split("<->")] if "<->" in code_id_entry else [code_id_entry]
            if any(item.get("source_c_code_id") == code_unique_names for item in trans_metadata): continue
            print("Processing code_ids: ", code_unique_names)
            code_trans(code_unique_names)


                
        
    def trans_PA(self):  
        trans_metadata_path, entities_path, relationships_path, c_topo_sort_str = self.translation_setup();
        
        # Load the trans meta data      
        with open(trans_metadata_path, 'r', encoding='utf-8') as f:
            trans_metadata = [json.loads(line.strip()) for line in f.readlines()]

        # Load `free` function list
        freeFunction_list = []
        for meta in trans_metadata:
            if "trans_rust_code" in meta and meta['trans_rust_code'] == "Free_Function":
                free_function_name = [source_c_code_id.split("#")[0] for source_c_code_id in meta['source_c_code_id']]
                freeFunction_list.extend(free_function_name)
                
        # Load the call Graph
        call_graph_list = self.call_graph_load(relationships_path, entities_path)
        func_SA_json_path, struct_SA_json_path = self.SA_result_path()
        
        
        ## Start Trans
        def code_trans(code_unique_names):
            nonlocal trans_metadata
            source_called_name = []
            all_source_code_list = []
            var_typedef_TAG = False
            for code_unique_name in code_unique_names:
                source_code_type = call_graph_list[code_unique_name]["source_type"]
                source_code = call_graph_list[code_unique_name]["source_code"].strip()
                if (source_code_type == "variable" and not self.is_large_array(source_code)) or \
                (source_code_type == "typedef" and len(source_code.split("\n"))==1):
                    continue
                
                called_name_list = call_graph_list[code_unique_name]["source_called_name"]
                source_called_name.extend(called_name_list) 

                called_var_typedef = ""
                for called_name in called_name_list:
                    called_code_type = call_graph_list[called_name]["source_type"]
                    if called_code_type == "variable" and not self.is_large_array(call_graph_list[called_name]["source_code"].strip()):
                        called_source_code = call_graph_list[called_name]["source_code"].strip() + " // [NOTE: MAKE THIS VARIABLE TO LOCAL!]"
                        var_typedef_TAG = True
                        source_called_name.extend(call_graph_list[called_name]["source_called_name"]) 
                    elif called_code_type == "typedef" and len(call_graph_list[called_name]["source_code"].strip().split("\n"))==1:
                        called_source_code = call_graph_list[called_name]["source_code"].strip() + " // [NOTE: REPLACE THIS IN USAGE!]"
                        var_typedef_TAG = True
                        source_called_name.extend(call_graph_list[called_name]["source_called_name"])
                    else: called_source_code = ""
                    called_var_typedef = called_var_typedef + "\n" + called_source_code
                all_source_code_list.append(call_graph_list[code_unique_name]["source_code"].strip())
            
            if len(all_source_code_list)==0: return   
            source_c_code = "\n---\n".join(all_source_code_list)
            
            
            trans_rust_paths = [meta for meta in trans_metadata if meta['map_tag'] == "file" and meta['source'] == code_unique_names[0].split("#")[1]]
            assert len(trans_rust_paths) == 1, f"Error: No corresponding Rust code path found for {code_unique_names}"
            trans_rust_path = trans_rust_paths[0]['target'] 


            rust_depend_metas_dict = {}
            for called_unique_name in source_called_name:
                rust_depend_meta = [meta for meta in trans_metadata if meta['map_tag'] == "code" and called_unique_name in meta['source_c_code_id']]
                for meta in rust_depend_meta:

                    meta_key = (tuple(meta['source_c_code_id']), meta['trans_rust_path'])
                    rust_depend_metas_dict[meta_key] = meta

            rust_depend_metas = list(rust_depend_metas_dict.values())
            

            source_c_code_info = (call_graph_list, source_c_code, source_code_type)
            SA_result = self.obtain_SA_result(source_c_code_info, code_unique_names, func_SA_json_path, struct_SA_json_path)
            
            trans_rust_code, toml_depend, trans_rust_code_context = "","",""
            verf_Result = "Success"
            

            token_count = self.generator.get_token_count(source_c_code)
            truncate_tag = False
            if token_count and token_count > 10000:
                half_length = 5000
                truncate_tag = True
                truncate_pos = source_c_code.rfind('\n', 0, half_length)
                if truncate_pos == -1: truncate_pos = half_length
                trun_source_c_code = source_c_code[:truncate_pos] + "\n// ... [TOO LONG] ..."
                if source_c_code.strip().endswith("}"):source_c_code = trun_source_c_code + "\n}"
                else: source_c_code = trun_source_c_code
                
            judged_source_c_code = ""
            # DEBUG
            if source_code_type == "function":
                called_code_context = ""
                for called_unique_name in source_called_name:
                    called_code_context = called_code_context + "\n------\n" + call_graph_list[called_unique_name]["source_code"]
                pointToInfo = ""
                for SA in SA_result.split("\n"):
                    if "pointTo" in SA: 
                        pointToInfo = pointToInfo + "\n" + SA
                

                freeAted_source_c_code = self.free_annotation(source_c_code, freeFunction_list)
                judged_source_c_code = self.translator._free_judge(freeAted_source_c_code, called_code_context, pointToInfo)
            
            if judged_source_c_code == "Free_Function":
                free_function_name = [source_c_code_id.split("#")[0] for source_c_code_id in code_unique_names]
                freeFunction_list.extend(free_function_name)
                trans_metadata.append({"trans_rust_code_context": "", "rust_definition_name": "","map_tag": "code", "Verfi_Tag": "Free_Function",
                                        "trans_rust_code": "Free_Function", "source_code_type":source_code_type,
                                        "source_c_code_id": code_unique_names, "trans_rust_path": trans_rust_path})

            else:
                to_trans_c_code = judged_source_c_code if judged_source_c_code != "" else source_c_code
                to_trans_c_code = called_var_typedef.strip() + "\n" + to_trans_c_code.strip()

                rust_code_path = os.path.join(self.args.trans_project_path, self.args.source_project_name, trans_rust_path)
                with open(rust_code_path, 'r', encoding='utf-8') as f:
                    rust_file_code = f.read()            
                

                trans_rust_code_temp, toml_depend = \
                    self.translator._code_trans(to_trans_c_code, rust_depend_metas, code_unique_names, rust_file_code.strip(), SA_result, var_typedef_TAG)


                trans_rust_code = self.remove_duplicate_trans(trans_rust_code_temp, trans_metadata)
                trans_rust_code_context = self.rust_parser.extract_item_content(trans_rust_code)
                if len(trans_rust_code_context) == 0: trans_rust_code_context  = trans_rust_code
            
                self.git_manager.ensure_git_repo(self.rust_project_path)
                
                initial_commit = self.git_manager.git_save_state(self.rust_project_path, f"Initial translation for {code_unique_names}")
                
                written_rust =  self.trans_rust_code_write(trans_rust_code,trans_rust_path, "")
                self.toml_write(toml_depend)

                trans_metadata.append({"source_c_code_id": code_unique_names, "map_tag": "code", "source_code_type":source_code_type,
                                       "trans_rust_path": trans_rust_path, "trans_rust_code_context": trans_rust_code_context,
                                       "trans_rust_code": written_rust[0],
                                       "rust_definition_name": self.rust_parser.get_rust_definitions(trans_rust_code)
                                       })
            
                verf_Result = self.rust_compile_verfication()
                original_trans_metadata = copy.deepcopy(trans_metadata)                
                fixedError = []
                error_count = 0
                compilation_success = False 
                

                try:
                    while verf_Result != "Success":
                        error_count = error_count + 1
                        if error_count > self.Max_fixCount or truncate_tag:
                            logger.warning(f"Reach the maximum number of attempts ({self.Max_fixCount}), exit the repair loop")
                            break
                        
                        fixedError.append(verf_Result)
                        

                        error_log = verf_Result['error_log']
                        primary_item = verf_Result['primary_item']

                        fix_rust_code_context = "\n==========\n".join([meta['trans_rust_code'].strip() for meta in rust_depend_metas])


                        cycle_metas = [meta for meta in trans_metadata if "trans_rust_code" in meta and primary_item.strip() in meta['trans_rust_code']]
                        if len(cycle_metas)!=0 and len(cycle_metas[0]['rust_definition_name'])>1: 
                            ex_context = cycle_metas[0]['trans_rust_code'].replace(primary_item.strip(), "")
                            fix_rust_code_context = ex_context + "\n==========\n" + fix_rust_code_context
                        
                        related_item = self.translator._error_related_code(error_log, primary_item, fix_rust_code_context)
                        rust_item = primary_item+"\n"+related_item
                        if "cannot find " in error_log:
                            fix_SA_info = self.extract_fileInfo(rust_item, trans_metadata)
                        else:
                            fix_SA_info = self.extract_SA4Error(rust_item, trans_metadata, call_graph_list, func_SA_json_path, struct_SA_json_path)

                        fixed_rust_list,toml_de = self.translator._rust_error_fix(error_log, primary_item, related_item, fix_SA_info)
                        if len(toml_de)!=0: self.toml_write(toml_de)

                        trans_metadata = self.replaceItem_fixed_rust(fixed_rust_list, trans_metadata, verf_Result)


                        fix_commit = self.git_manager.git_save_state(
                            self.rust_project_path, 
                            f"Fix attempt {len(fixedError)} for {code_unique_names}"
                        )
                        
                        verf_Result = self.rust_compile_verfication()
                    

                    if verf_Result == "Success":
                        compilation_success = True

                except Exception as e:
                    logger.error(f"Exception stack trace:\n{traceback.format_exc()}")
     
    
                if not compilation_success:
                    trans_metadata = self._handle_translation_failure(
                        trans_metadata, original_trans_metadata, initial_commit,
                        to_trans_c_code, source_code_type, rust_depend_metas,
                        code_unique_names, rust_file_code.strip(), SA_result,
                        trans_rust_path, verf_Result, written_rust
                    )
    
                if len(fixedError) == 0: verfi_tag = "No_Fix_Compile_Success"
                elif verf_Result == "Success": verfi_tag = f"Fixed_{len(fixedError)}_Compile_Success"
                else: verfi_tag = f"Fixed_{len(fixedError)}_Compile_Failed"
                if truncate_tag: verfi_tag = "Fixed_truncate_Compile_Failed"
                
                trans_metadata[-1]["Verfi_Tag"] = verfi_tag
                                
            with open(trans_metadata_path, 'a', encoding='utf-8') as f:
                json.dump(trans_metadata[-1], f, ensure_ascii=False)
                f.write('\n')
                
        for code_id_entry in tqdm(c_topo_sort_str.split("\n"), desc="Processing code_ids"):
            code_unique_names = [id.strip() for id in code_id_entry.split("<->")] if "<->" in code_id_entry else [code_id_entry]
            if any(item.get("source_c_code_id") == code_unique_names for item in trans_metadata): continue
            print("Processing code_ids: ", code_unique_names)
            code_trans(code_unique_names)


    def _handle_translation_failure(self, trans_metadata, original_trans_metadata, initial_commit, 
                                to_trans_c_code, source_code_type, rust_depend_metas, 
                                code_unique_names, rust_file_code, SA_result, trans_rust_path, verf_Result, init_trans):
        logger.warning(f"Translation failed, revert to stub implementation")
        trans_metadata_updated = original_trans_metadata
        if initial_commit:
            self.git_manager.git_restore_state(self.rust_project_path, initial_commit)
        

        trans_stub_rust_code, _, _ = \
            self.translator._stub_trans(to_trans_c_code, source_code_type, rust_depend_metas, 
                                    code_unique_names, rust_file_code.strip(), SA_result)
        written_rust = self.trans_rust_code_write(trans_stub_rust_code, trans_rust_path, "")
        
    
        trans_rust_code_copy = trans_metadata[-1]["trans_rust_code"]
        trans_metadata_updated[-1]["trans_stub_rust_code"] = trans_rust_code_copy
        trans_metadata_updated[-1]["trans_rust_code"] = trans_stub_rust_code
        trans_metadata_updated[-1]["trans_rust_code_context"] = trans_stub_rust_code
        trans_metadata_updated[-1]["try_trans_error"] = init_trans[0]
    
        if isinstance(verf_Result, dict) and 'error_log' in verf_Result:
            trans_metadata_updated[-1]["error_log"] = verf_Result['error_log']
        
        trans_metadata_updated[-1]["rust_definition_name"] = self.rust_parser.get_rust_definitions(trans_stub_rust_code)
        
        return trans_metadata_updated


    def is_large_array(self, source_code, min_elements=2):

        if '[' not in source_code or ']' not in source_code:
            if '{' not in source_code or '}' not in source_code:
                return False
    
        try:
            init_content = source_code[source_code.find('{')+1:source_code.rfind('}')]
            
            comma_count = init_content.count(',')
            element_count = comma_count + 1  
            
            is_large = element_count >= min_elements
            
            if is_large:
                array_name = source_code.split('[')[0].strip().split()[-1]
                logger.info(f"Detect large array: {array_name}, element count: {element_count}, will be translated rather than localized")
            
            return is_large
        except Exception as e:
            logger.warning(f"Error parsing array: {e}")
            return False


    def split_code_groups(self, code_unique_names, group_size=3):
        if len(code_unique_names) <= 6:
            return [code_unique_names]
        
        groups = []
        for i in range(0, len(code_unique_names), group_size):
            group = code_unique_names[i:i + group_size]
            groups.append(group)
        
        return groups

    def remove_duplicate_trans(self, trans_rust_code, trans_metadata):
        trans_rust_definition_name = self.rust_parser.get_rust_definitions(trans_rust_code)
        existing_definitions = set()
        for meta in trans_metadata:
            if 'rust_definition_name' in meta and meta.get('map_tag') == 'code':
                for name in meta['rust_definition_name']:
                    existing_definitions.add(name)
        definitions_to_remove = [name for name in trans_rust_definition_name if name in existing_definitions]
        if len(definitions_to_remove) == 0: return trans_rust_code
        rust_items = self.rust_parser.find_rust_items(trans_rust_code)
        code_lines = trans_rust_code.split('\n')
        

        items_to_remove = [item for item in rust_items if item['name'] in definitions_to_remove]
        items_to_remove.sort(key=lambda x: x['start_line'], reverse=True)
        
        for item in items_to_remove:
            start_line = item['start_line']
            end_line = item['end_line']
            

            del code_lines[start_line-1:end_line]
        

        filtered_trans_rust_code = '\n'.join(code_lines)
        return filtered_trans_rust_code



    def SA_result_path(self):

        expanded_pj_path = f"{self.args.source_project_path}_expanded_dealed"
        run_sh_path = os.path.join(self.args.root_dir, "script/SA/backup/run.sh")


        analysis_output_dir = os.path.join(expanded_pj_path, "svf_analysis_output")
        struct_SA_json_path= os.path.join(analysis_output_dir, "struct_analysis_report.json")
        func_SA_json_path = os.path.join(analysis_output_dir, "func_analysis_report.json")
        
        if os.path.exists(struct_SA_json_path) and os.path.exists(func_SA_json_path):
            return func_SA_json_path, struct_SA_json_path
        
        func_SA_path = "backup/PA_func.cpp"
        struct_SA_path = "backup/PA_struct.cpp"
        
        for path in (expanded_pj_path, run_sh_path):
            if not os.path.exists(path):
                raise FileExistsError(f"{path} 不存在")
        
        logger.info(f"Start executing SVF static analysis...")
        try:
            for cpp_path in (func_SA_path, struct_SA_path):
                cmd = ['bash', run_sh_path, expanded_pj_path, cpp_path]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=self.args.root_dir  
                )
                if result.returncode == 0:
                    logger.info("SVF analysis script executed successfully!")
                else:
                    logger.error(f"{cpp_path} executed failed")
                    if result.stdout:
                        logger.error(f"SVF stdout:\n{result.stdout}")
                    if result.stderr:
                        logger.error(f"SVF stderr:\n{result.stderr}")
                    raise Exception(f"SVF analysis script executed failed, return code: {result.returncode}")
        
        except Exception as e:
            raise Exception(f"SVF analysis script executed failed: {e}")


        return func_SA_json_path, struct_SA_json_path    
      
    def normalize_points_to(self, points_to_list):
        normalized = {}
        
        for points_to in points_to_list:
            base_type = points_to.replace('*', '').strip()
            
            if base_type in normalized:
                if '*' in points_to and '*' not in normalized[base_type]:
                    normalized[base_type] = points_to
            else:
                normalized[base_type] = points_to
                
        return list(normalized.values())

    def func_pointTo_Path_result(self, callsites_list, c_path, param_name):

        pointTo_result = ""
        points_to_set = set()
        
        for callsite in callsites_list:
            if 'points_to' in callsite:
                points_to_set.add(callsite['points_to'])
        
        # Standardize and remove duplicate points_to list
        unique_points_to = self.normalize_points_to(list(points_to_set))
        
        for points_to in unique_points_to:
            pointTo_result += f"`{param_name}` pointTo: {points_to}\n"
            
        return pointTo_result

    def obtain_SA_result(self, source_c_code_info, code_unique_names, func_SA_json_path, struct_SA_json_path):
        logger.info(f"Get static analysis result for {code_unique_names}")
        call_graph_list, source_c_code, source_code_type = source_c_code_info

        c_path = f"{self.args.source_project_path}_expanded_dealed"
        
        SA_result = []

        for code_unique_name in code_unique_names:
            code_name = code_unique_name.split("#")[0]
            if source_code_type in ['union','struct','enum']: 
                with open(struct_SA_json_path, 'r') as json_file:
                    struct_SA_cont = json.load(json_file)
                struct_info = ""
                struct_name = ""
                for key in struct_SA_cont.keys():
                    if f".{code_name}" in key:
                        struct_name = key
                        struct_info = struct_SA_cont[key]
                        break
                if len(struct_info) == 0: continue
                print(f"find struct info for {code_name}")
                # Get struct info from struct_info
                struct_sa_result = ""
                for field in struct_info['fields']:
                    specific_name = self.c_parser.get_c_member_name_by_index(source_c_code, field['field_index'])
                    field_name = field['field_name']
                    Mut_Own_result, field_path_result = "", ""
                    if field['is_pointer'] and field['ownership'] == "Owning":
                        Mut_Own_result = f"{struct_name}_{specific_name} is Nullable, and {field['ownership']} pointer"
                        field_usage_paths = (struct_info.get('usage_paths') or {}).get(field_name)
                        if field_usage_paths:
                            field_path_result = self.struct_path_result(field_usage_paths, c_path)
                    elif field['is_pointer'] and field['ownership'] == "Borrowed": # Remind the model to express the lifetime of this struct member
                        Mut_Own_result = f"{struct_name}_{specific_name} is Nullable, Borrowed and {field['mutability']} pointer, declared as Option<&T> or Option<&mut T>; **Requires Lifetime Annotation**"
                        field_usage_paths = (struct_info.get('usage_paths') or {}).get(field_name)
                        if field_usage_paths:
                            field_path_result = self.struct_path_result(field_usage_paths, c_path)
                        
                    struct_sa_result = struct_sa_result + "\n\n" + Mut_Own_result + "\n" + field_path_result
                
                SA_result.append(f"====`{code_name}` Requirements====\n{struct_sa_result.strip()}")
            
            elif source_code_type in ['function']:
                with open(func_SA_json_path, 'r') as josn_file:
                    func_SA_cont = json.load(josn_file)
                function_analysis = func_SA_cont['function_analysis']
                if code_name not in function_analysis: continue
                func_info = function_analysis[code_name]
                parameters_list = func_info['parameters']
                param_SA_result = []
                for paramInfo in parameters_list:
                    if paramInfo['ownership'] == "Owning":
                        param_result = f"{paramInfo['param_name']} is Nullable, and Owning pointer"
                        callsites_list = paramInfo['callsites']
                        pointTo_Usage = self.func_pointTo_Path_result(callsites_list, c_path, paramInfo['param_name'])
                        if pointTo_Usage.strip():
                            param_result = f"{param_result}\n{pointTo_Usage.strip()}"
                    elif paramInfo['ownership'] == "Borrowed": 
                        param_result = f"{paramInfo['param_name']} is Nullable, Borrowed and {paramInfo['mutability']} pointer."
                        callsites_list = paramInfo['callsites']
                        pointTo_Usage = self.func_pointTo_Path_result(callsites_list, c_path, paramInfo['param_name'])
                        if pointTo_Usage.strip():
                            param_result = f"{param_result}\n{pointTo_Usage.strip()}"
                    else: 
                        param_result = ""
                    
                    if param_result:
                        param_SA_result.append(param_result)
                
                # Check parameter alias relationship
                alias_result = self.check_param_aliasing(parameters_list)
                if alias_result:
                    alias_entries = []
                    for alias in alias_result:
                        param1 = alias["param1"]
                        param2 = alias["param2"]
                        
                        # Get struct field details of parameter 1
                        param1_idx = next((i for i, p in enumerate(parameters_list) if p.get('param_id') == param1["id"]), -1)
                        if param1_idx != -1:
                            param1_fields = self.get_field_details(parameters_list[param1_idx], call_graph_list)
                        else:
                            param1_fields = {}
                            
                        # Get struct field details of parameter 2
                        param2_idx = next((i for i, p in enumerate(parameters_list) if p.get('param_id') == param2["id"]), -1)
                        if param2_idx != -1:
                            param2_fields = self.get_field_details(parameters_list[param2_idx], call_graph_list)
                        else:
                            param2_fields = {}
                        
                        # Determine access type description
                        if param1['mutability'] == 'Mutable' and param2['mutability'] == 'Mutable':
                            access_conflict = "both require mutable access"
                        elif param1['mutability'] == 'Mutable':
                            access_conflict = f"`{param1['name']}` requires mutable access and `{param2['name']}` requires immutable access"
                        elif param2['mutability'] == 'Mutable':
                            access_conflict = f"`{param1['name']}` requires immutable access and `{param2['name']}` requires mutable access"
                        else:
                            access_conflict = "both require immutable access"
                        
                        # Build alias information description, according to the specified format
                        alias_desc = f"`{param1['name']}` and `{param2['name']}` can point to the Same Object, where {access_conflict}."
                        

                        if param1['mutability'] == 'Mutable' or param2['mutability'] == 'Mutable':
                            alias_desc += " This will cause borrowing rule conflicts."
                        
                        alias_desc += "\nRefactor parameters based on actual usage:"
                        if param1_fields.get('fields'):
                            field_names = [field.get('field_name', field.get('field_id', 'unknown')) for field in param1_fields.get('fields', [])]
                            if field_names:
                                if len(field_names) == 1:
                                    alias_desc += f"\n - `{param1['name']}` accessed field: `{field_names[0]}`"
                                else:
                                    alias_desc += f"\n - `{param1['name']}` accessed fields: " + ", ".join([f"`{name}`" for name in field_names])
                        else:
                            alias_desc += f"\n - `{param1['name']}` accessed fields: none identified"
                            
                        if param2_fields.get('fields'):
                            field_names = [field.get('field_name', field.get('field_id', 'unknown')) for field in param2_fields.get('fields', [])]
                            if field_names:
                                if len(field_names) == 1:
                                    alias_desc += f"\n - `{param2['name']}` accessed field: `{field_names[0]}`"
                                else:
                                    alias_desc += f"\n - `{param2['name']}` accessed fields: " + ", ".join([f"`{name}`" for name in field_names])
                        else:
                            alias_desc += f"\n - `{param2['name']}` accessed fields: none identified"
                        
                        alias_entries.append(alias_desc)
                    
                    alias_SA_result = f"====`{code_name}` Parameter Aliasing==== [MORE ATTENTION!!]\n" + "\n\n----\n\n".join(alias_entries)
                    SA_result.append(alias_SA_result)
                
                ret_list = func_info['returns']
                ret_results = []
                for returnInfo in ret_list:
                    if returnInfo['ownership'] == "Owning":
                        ret_result = f"`{code_name}` Return is Nullable, and Owning pointer"
                        ret_results.append(ret_result)
                    elif returnInfo['ownership'] == "Borrowed":
                        if returnInfo['life_result'] != "No_depend":
                            ret_result = f"`{code_name}` Return is Nullable, Borrowed and {returnInfo['mutability']} pointer; **Requires Lifetime Annotation as {returnInfo['life_result']}**."
                        else:
                            ret_result = f"`{code_name}` Return is Nullable, Borrowed and {returnInfo['mutability']} pointer."
                        ret_results.append(ret_result)
                
                if len(param_SA_result):
                    param_section = f"====`{code_name}` Parameter Requirements====\n" + "\n----\n".join(param_SA_result)
                    SA_result.append(param_section)
                if len(ret_results):
                    ret_section = f"====`{code_name}` Return Requirements====\n" + "\n".join(ret_results)
                    SA_result.append(ret_section)
        SA_result_striped = "\n\n".join(SA_result)
        
        
        SA_result_list = SA_result_striped.split("\n")
        Trans_not_RA = []
        for sa_item in SA_result_list:
            if "is Nullable, and " not in sa_item and "is Nullable, Borrowed and " not in sa_item and "Return is Nullable, Borrowed and " not in sa_item and "Return is Nullable, and Owning pointer" not in sa_item:
                Trans_not_RA.append(sa_item)
            elif "Requirements" in sa_item:
                Trans_not_RA.append(sa_item)
            else:
                sa_item = sa_item.split(", ")[0]
                Trans_not_RA.append(sa_item)

        Trans_not_PU = []
        for sa_item in SA_result_list:
            if "is Nullable, and " in sa_item or "is Nullable, Borrowed and " in sa_item or "Return is Nullable, Borrowed and " in sa_item or "Return is Nullable, and Owning pointer" in sa_item:
                Trans_not_PU.append(sa_item)
            elif "Requirements" in sa_item:
                Trans_not_PU.append(sa_item)

        if "Trans_not_PU" in self.args.translate_mode:
            return "\n\n".join(Trans_not_PU)
        elif "Trans_not_RA" in self.args.translate_mode:
            return "\n\n".join(Trans_not_RA) 
        else:
            return SA_result_striped


    def check_param_aliasing(self, parameters_list):
        result = []
        
        for i in range(len(parameters_list)):
            for j in range(i + 1, len(parameters_list)):
                param1 = parameters_list[i]
                param2 = parameters_list[j]
                
                # Only check pointer type parameters
                if param1.get('ownership') not in ['Borrowed', 'Owning'] or param2.get('ownership') not in ['Borrowed', 'Owning']:
                    continue
                    
                # Check if two parameters may point to the same object
                param1_points_to = []
                param2_points_to = []
                
                # Collect param1's points_to values
                for callsite in param1.get('callsites', []):
                    if 'points_to' in callsite:
                        points_to = callsite['points_to'].replace('*', '')
                        param1_points_to.append(points_to)
                
                for callsite in param2.get('callsites', []):
                    if 'points_to' in callsite:
                        points_to = callsite['points_to'].replace('*', '')
                        param2_points_to.append(points_to)
                
                common_points_to = set(param1_points_to) & set(param2_points_to)
                if common_points_to:
                    param1_mutable = param1.get('mutability') == 'Mutable'
                    param2_mutable = param2.get('mutability') == 'Mutable'
                    
                    if param1_mutable or param2_mutable:
                        alias_info = {
                            "param1": {
                                "name": param1.get('param_name'),
                                "id": param1.get('param_id'),
                                "mutability": param1.get('mutability'),
                            },
                            "param2": {
                                "name": param2.get('param_name'),
                                "id": param2.get('param_id'),
                                "mutability": param2.get('mutability'),
                            },
                            "common_points_to": list(common_points_to)
                        }
                        result.append(alias_info)
        
        return result if result else None
    

    def get_field_details(self, param, call_graph_list):

        result = {}
        
        if 'struct_member_usage' not in param:
            return result
            
        struct_type = param['struct_member_usage'].get('struct_type')
        accessed_fields = param['struct_member_usage'].get('accessed_fields', [])
        
        if not struct_type or not accessed_fields:
            return result
            
        struct_code = ""
        for unique_name, info in call_graph_list.items():
            if info["source_type"] in ["struct", "union"] and struct_type+"#" in unique_name:
                struct_code = info["source_code"]
                break
                
        if not struct_code:
            return {"struct_type": struct_type, "fields": [{"field_id": field, "field_name": field} for field in accessed_fields]}
            
        fields = []
        for field in accessed_fields:
            if field.startswith("field_"):
                try:
                    index = int(field.split("_")[1])
                    field_name = self.c_parser.get_c_member_name_by_index(struct_code, index)
                    fields.append({"field_id": field, "field_name": field_name, "index": index})
                except (ValueError, IndexError):
                    continue
                
        return {
            "struct_type": struct_type,
            "fields": fields
        }
    
    def struct_path_result(self,field_usage_paths, c_path):
        if not field_usage_paths:
            return ""
        
        # Select the longest path from all paths, as the return path
        all_path_list = []
        for item_dict in field_usage_paths:
            paths_list = item_dict['paths']
            all_path_list.extend(paths_list)
        if not all_path_list:
            return ""
        longest_path = max(all_path_list, key=len)[::-1]
        
        path_parts = []
        for nodeInfo in longest_path:
            if ':' not in nodeInfo: continue
            file_name, line_str = nodeInfo.rsplit(":", 1)
            c_code_file = os.path.join(c_path, file_name) 
            with open(c_code_file, 'r') as f:
                lines = f.readlines()
            if lines[int(line_str) - 1].strip() not in path_parts:
                path_parts.append(lines[int(line_str) - 1].strip())
        path_parts_str = "-->".join(path_parts)           
            
        return "UsagePath: " + path_parts_str
            
                 
    def rust_compile_verfication(self):
        
        logger.info(f"Start executing cargo check verification on Rust project: {self.rust_project_path}")
        os.chdir(self.rust_project_path)
        
        # Execute cargo check command
        result = subprocess.run(
            "cargo clean && cargo check",
            capture_output=True,
            text=True,
            timeout=300,
            shell=True
        )
        os.chdir(current_dir)
        if result.returncode == 0:
            logger.info("cargo check executed successfully, project compilation check passed")
            return "Success"
        else:
            logger.error(f"cargo check executed failed, return code: {result.returncode}")
            error_info = result.stderr
            error_blocks = self.extract_error_blocks(error_info)
            if len(error_blocks) == 0:
                raise Exception(f"No error information collected: {error_blocks}")
            
            for error_block in error_blocks:
                if "is defined multiple times" in error_block or "E0428" in error_block:
                    error_location = self.extract_error_locations(error_block)
                    if error_location and self.handle_duplicate_definition_error(error_block, error_location):
                        logger.info("Successfully handled duplicate definition error, re-verify compilation")
                        return self.rust_compile_verfication()
            
            primary_item, combined_errors = self.get_errors_for_item(error_blocks)
            error_location = self.extract_error_locations(error_blocks[0])
            return {"error_log":combined_errors, "primary_item":primary_item, "loca_info":error_location}

    def extract_error_blocks(self, stderr_output):
        if not stderr_output or stderr_output.strip() == "":
            return []
        
        # Error block starts with: error[EXXXX]: or error: 
        error_pattern = r'^error(?:\[[^\]]+\])?:'
        
        lines = stderr_output.split('\n')
        error_blocks = []
        current_block = []
        in_error_block = False
        
        for i, line in enumerate(lines):
            if re.match(error_pattern, line.strip()):
                if current_block:
                    error_blocks.append('\n'.join(current_block))
                current_block = [line]
                in_error_block = True
            elif in_error_block:
                # Check if the error block ends
                if (re.match(r'^warning(?:\[[^\]]+\])?:', line.strip()) or
                    line.strip().startswith('For more information') or
                    line.strip().startswith('error: could not compile') or
                    (line.strip() == '' and i + 1 < len(lines) and 
                    lines[i + 1].strip() != '' and not lines[i + 1].startswith(' ') and
                    not lines[i + 1].startswith('\t') and
                    not re.match(error_pattern, lines[i + 1].strip()))):
                    # Error block ends
                    if current_block:
                        error_blocks.append('\n'.join(current_block))
                        current_block = []
                    in_error_block = False
                else:
                    # Continue adding to the current error block
                    current_block.append(line)
        
        if current_block:
            error_blocks.append('\n'.join(current_block))
        
        cleaned_blocks = []
        for block in error_blocks:
            if "consider importing" in block.rstrip():
                cleaned_block = block.rstrip()
            else:
                cleaned_block = block.rstrip().split("help: consider")[0]
            if cleaned_block:
                cleaned_blocks.append(cleaned_block)
        
        return cleaned_blocks

    def extract_error_locations(self, error_block):
        if not error_block or error_block.strip() == "":
            return []
        
        # Match "--> file path: line number: column number" this pattern
        location_pattern = r'-->\s+([^:]+):(\d+):\d+'
        
        matches = re.finditer(location_pattern, error_block)
        
        locations = []
        seen = set()  
        
        for match in matches:
            file_path = match.group(1)
            line_number = int(match.group(2))
            
            location_key = f"{file_path}:{line_number}"
            
            if location_key not in seen:
                locations.append({
                    'file_path': file_path,
                    'line_number': line_number
                })
                seen.add(location_key)  # Mark as added
        
        return locations

    def get_errors_for_item(self, error_blocks):

        if not error_blocks:
            return "", "", []
        

        first_locations = self.extract_error_locations(error_blocks[0])
        if not first_locations:
            return "", error_blocks[0]  
        
        primary_location = first_locations[0]
        file_path = primary_location['file_path']
        line_number = primary_location['line_number']
        

        rust_file_path = os.path.join(self.rust_project_path, file_path)
        primary_item, item_range = self.get_rust_code_by_line_number(rust_file_path, line_number)
        

        related_errors = []
        for error_block in error_blocks:
            locations = self.extract_error_locations(error_block)
            if not locations:
                continue
            
            for location in locations:
                loc_file_path = location['file_path']
                loc_line_number = location['line_number']
                
                if loc_file_path != file_path:
                    continue
                
                if item_range and (item_range[0] <= loc_line_number <= item_range[1]):
                    related_errors.append(error_block)
                    break  
        
        if not related_errors:
            related_errors = [error_blocks[0]]
        
        combined_errors = "\n\n".join(related_errors)
        
        return primary_item, combined_errors



    def handle_duplicate_definition_error(self, error_log, error_location):
        
        if "is defined multiple times" not in error_log and "E0428" not in error_log:
            return False
        
        name_match = re.search(r"the name [`']([^'`]+)[`'] is defined multiple times", error_log)
        if not name_match:
            return False
        
        duplicate_name = name_match.group(1)
        logger.info(f"Detect duplicate definition error: {duplicate_name}")
        
        # Extract the first definition location
        prev_def_match = re.search(r"(\d+)\s*\|[^\n]*\n\s*\|[^\n]*previous ", error_log)
        if not prev_def_match:
            return False
        
        line_number = int(prev_def_match.group(1))
        
        file_path_match = re.search(r"-->\s+([^:]+):", error_log)
        if not file_path_match:
            logger.warning("Cannot extract file path from error information")
            return False
        
        file_path = file_path_match.group(1)
        
        rust_file_path = os.path.join(self.rust_project_path, file_path)
        if not os.path.exists(rust_file_path):
            logger.warning(f"File does not exist: {rust_file_path}")
            return False
        
        # Get the first definition code item
        first_def_item, item_range = self.get_rust_code_by_line_number(rust_file_path, line_number)
        if not first_def_item or not item_range:
            logger.warning(f"Cannot get code item at line {line_number}")
            return False
        
        # Read file content
        with open(rust_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Remove the first definition code item
        start_line, end_line = item_range
        logger.info(f"Remove duplicate definition: {duplicate_name} in {file_path} at line {start_line} to {end_line}")
        
        # Create new file content, excluding the duplicate definition item
        new_lines = lines[:start_line-1] + lines[end_line:]
        
        # Write back to file
        with open(rust_file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        return True


    def extract_SA4Error(self, rust_item:str, trans_metadata, call_graph_list,func_SA_json_path, struct_SA_json_path)->str:
        SA_List = []
        rust_item_definition_names = self.rust_parser.get_rust_definitions(rust_item)
        for def_name_str in rust_item_definition_names:
            if def_name_str in [name for meta in trans_metadata if 'rust_definition_name' in meta for name in meta.get('rust_definition_name', [])]:
                related_meta = next((meta for meta in trans_metadata 
                                    if 'rust_definition_name' in meta and def_name_str in meta['rust_definition_name']), None)
                
                if related_meta and 'source_c_code_id' in related_meta and 'source_code_type' in related_meta:
                    source_c_code_id = related_meta['source_c_code_id']
                    source_code_type = related_meta['source_code_type']
                    if source_code_type in ["function"]: # Only focus on function type
                        source_c_code_info = call_graph_list, "", source_code_type
                        SA_Result = self.obtain_SA_result(source_c_code_info, source_c_code_id, func_SA_json_path, struct_SA_json_path)
                        if len(SA_Result):
                            SA_List.append(SA_Result)
        return "\n".join(SA_List)
    
    def extract_fileInfo(self, rust_item:str, trans_metadata):
        Info_List = []
        rust_item_definition_names = self.rust_parser.get_rust_definitions(rust_item)
        for def_name_str in rust_item_definition_names:
            if def_name_str in [name for meta in trans_metadata if 'rust_definition_name' in meta for name in meta.get('rust_definition_name', [])]:
                related_meta = next((meta for meta in trans_metadata 
                                    if 'rust_definition_name' in meta and def_name_str in meta['rust_definition_name']), None)
                if related_meta and 'trans_rust_code_context' in related_meta and 'trans_rust_path' in related_meta:

                    trans_rust_path = related_meta['trans_rust_path']
                    trans_rust_code_context = related_meta['trans_rust_code_context']
                    fileInfo = f"[NOTE] {trans_rust_path} Defined:\n{trans_rust_code_context}"
                    Info_List.append(fileInfo)
        return "\n===\n".join(Info_List)
    
    # Function to replace item body
    def replaceItem_fixed_rust(self, fixed_rust_list, trans_metadata, verf_Result):
        for fixed_rust in fixed_rust_list:
            fixed_rust_defi_name_tuple = list(fixed_rust.keys())[0]  # Get tuple, e.g. ('BinnStruct',)
            fixed_rustCode = fixed_rust[fixed_rust_defi_name_tuple]  
            
            # Convert tuple to list, e.g. ['BinnStruct']. Because trans_metadata stores list
            fixed_rust_defi_name = list(fixed_rust_defi_name_tuple) 
            
            if fixed_rust_defi_name == ["LINE"]: 
                loca_info = verf_Result["loca_info"]
                error_pri_path = loca_info[0]['file_path']
                error_pri_line = loca_info[0]['line_number']
                rust_file_path = os.path.join(self.rust_project_path, error_pri_path)
                with open(rust_file_path, 'r', encoding='utf-8') as f:
                    rust_code_lines = f.readlines()
                with open(rust_file_path, 'r', encoding='utf-8') as f:
                    rust_code_lines = f.readlines()
                    
                if fixed_rustCode.strip().startswith("use "):
                    use_already_exists = False
                    for i, line in enumerate(rust_code_lines):
                        if line.strip() == fixed_rustCode.strip():
                            use_already_exists = True
                            break
                        if i > 0 and not line.strip().startswith("use ") and line.strip():
                            break
                    
                    if not use_already_exists:
                        rust_code_lines.insert(0, fixed_rustCode.strip() + '\n')
                else:
                    rust_code_lines[error_pri_line - 1] = fixed_rustCode + '\n'
                    
                with open(rust_file_path, 'w', encoding='utf-8') as f:
                    f.write(''.join(rust_code_lines))
                continue
                
            fixed_use_stmt, fixed_code_stmt = self.rust_parser.separate_use_statements_with_lines(fixed_rustCode)

            fixed_items = self.rust_parser.find_rust_items("\n".join(fixed_code_stmt))
            
            sorted_fixed_items = sorted(fixed_items, key=lambda x: (x['start_line'], -x['end_line']))
            fixed_code_map = {}
            nested_names = []  
            for i, fixed_item in enumerate(sorted_fixed_items):
                is_nested = False
                for j, other_item in enumerate(sorted_fixed_items):
                    if i != j and fixed_item['start_line'] > other_item['start_line'] and fixed_item['end_line'] <= other_item['end_line']:
                        is_nested = True
                        nested_names.append(fixed_item['name'])  
                        break
                if not is_nested:
                    fixed_start = fixed_item['start_line'] - 1
                    fixed_end = fixed_item['end_line']
                    fixed_item_code = "\n".join(fixed_code_stmt[fixed_start:fixed_end])
                    fixed_code_map[fixed_item['name']] = fixed_item_code
                    

            fixed_rust_defi_name = [name for name in fixed_rust_defi_name if name not in nested_names]
            candidate_names = fixed_rust_defi_name
            replace_metas = self._select_replace_metas(candidate_names, trans_metadata, verf_Result)
            if len(replace_metas) == 0:
                impl_for_stmt = [defi_name.split(" for ")[-1].split("<")[0].strip() for defi_name in candidate_names if " for " in defi_name]
                if len(impl_for_stmt) != 0:
                    candidate_names = impl_for_stmt
                    replace_metas = self._select_replace_metas(candidate_names, trans_metadata, verf_Result)

            if len(replace_metas) == 0:
                raise AssertionError(f"replace_metas: {replace_metas}")
            if len(replace_metas) > 1:
                matched_sources = [meta.get('source_c_code_id') for meta in replace_metas]
                logger.warning(f"Multiple metadata entries match {candidate_names}; selecting first best-scored candidate from {matched_sources}")
            replace_meta = replace_metas[0]
            to_be_replace_code_path = replace_meta['trans_rust_path']
            rust_file_path = os.path.join(self.rust_project_path, to_be_replace_code_path)
            with open(rust_file_path, 'r', encoding='utf-8') as f:
                rust_cont =  f.read()
            
            # Get all item_name and corresponding range in the file to be modified
            rust_items = self.rust_parser.find_rust_items(rust_cont)
            

            target_items = [item for item in rust_items if item['name'] in fixed_rust_defi_name]
            target_items.sort(key=lambda x: x['start_line'], reverse=True) 
            
            with open(rust_file_path, 'r', encoding='utf-8') as f:
                rust_code_lines = f.readlines()
                
            # Collect all original code segments to be replaced; [Modify existing code]
            replaced_codes = []
            # Replace according to the order of target_items (from back to front)
            for target_item in target_items:
                item_name = target_item['name']
                if item_name in fixed_code_map:
                    start_line, end_line = target_item['start_line'], target_item['end_line']
                    target_code = ''.join(rust_code_lines[start_line-1:end_line])
                    replaced_codes.append(target_code.strip())
                    replacement_code = fixed_code_map[item_name]
                    rust_code_lines[start_line-1:end_line] = [replacement_code + "\n"]

            target_item_names = [item['name'] for item in target_items]
            new_items = [item for item in fixed_items if item['name'] not in target_item_names and item['name'] in fixed_code_map]
            if new_items:
                for new_item in new_items:
                    item_name = new_item['name']
                    item_code = fixed_code_map[item_name]
                    rust_code_lines.append("\n\n" + item_code + "\n")
                      
            new_content = "\n".join(fixed_use_stmt) + "\n" + ''.join(rust_code_lines)
            with open(rust_file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                
            for replaced_code in replaced_codes:
                replace_meta['trans_rust_code'] = replace_meta['trans_rust_code'].replace(replaced_code, fixed_rustCode.strip())

            if new_items:
                new_code_combined = "\n\n".join([fixed_code_map[item['name']] for item in new_items if item['name'] in fixed_code_map])
                replace_meta['trans_rust_code'] = replace_meta['trans_rust_code'] + "\n" + new_code_combined
                new_definitions = self.rust_parser.get_rust_definitions(new_code_combined)
                replace_meta['rust_definition_name'] = replace_meta['rust_definition_name'] + new_definitions
                
            trans_rust_code_context = self.rust_parser.extract_item_content(replace_meta['trans_rust_code'])
            replace_meta['trans_rust_code_context'] = trans_rust_code_context

          
                
        return trans_metadata

    def _select_replace_metas(self, target_names, trans_metadata, verf_Result):
        error_path = None
        if isinstance(verf_Result, dict):
            loca_info = verf_Result.get("loca_info") or []
            if loca_info:
                error_path = loca_info[0].get("file_path")
        primary_item = verf_Result.get("primary_item", "") if isinstance(verf_Result, dict) else ""

        candidates = []
        for index, meta in enumerate(trans_metadata):
            rust_definition_names = meta.get('rust_definition_name')
            if not rust_definition_names:
                continue
            if isinstance(rust_definition_names, str):
                rust_definition_names = [rust_definition_names]

            overlap = len(set(target_names) & set(rust_definition_names))
            if overlap == 0:
                continue

            same_path = error_path is not None and meta.get('trans_rust_path') == error_path
            contains_primary = bool(primary_item and primary_item.strip() in meta.get('trans_rust_code', ''))
            candidates.append((overlap, same_path, contains_primary, index, meta))

        if not candidates:
            return []

        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
        best_score = candidates[0][:3]
        return [
            meta
            for overlap, same_path, contains_primary, _, meta in candidates
            if (overlap, same_path, contains_primary) == best_score
        ]


    def _replace_rust_code_in_file(self, old_code, new_code, file_path):
        rust_file_path = os.path.join(self.args.trans_project_path, self.args.source_project_name, file_path)
       
        with open(rust_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if old_code not in content: return False
        
        updated_content = content.replace(old_code, new_code)
        
        with open(rust_file_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        return True
          
    def trans_rust_code_write(self, trans_rust_code, trans_rust_path, trans_rust_path_cont):
        written_rust_code = ""
        rust_code_range = (0, 0)
        
        # If there is no code to write, return directly
        if not trans_rust_code: return written_rust_code, rust_code_range
        
    
        def code_write(path, code):
            nonlocal written_rust_code, rust_code_range
            rust_code_path = os.path.join(self.args.trans_project_path, self.args.source_project_name, path)
            
            # Separate use statements and actual code
            use_stmt, code_stmt = self.rust_parser.separate_use_statements_with_lines(code)

    
            code_content = "\n".join(code_stmt)
            written_rust_code = code_content
            
            with open(rust_code_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()
                
            # Check if the code already exists in the file
            if code_content in existing_content:
                pattern_text = re.escape(code_content)
                match = re.search(pattern_text, existing_content)
                text_before_match = existing_content[:match.start()]
                start_line = text_before_match.count('\n') + 1
                matched_text = match.group(0)
                end_line = start_line + matched_text.count('\n')
                rust_code_range = (start_line, end_line)
                return
            
            # Code does not exist, need to add to the file
            # Calculate line number range
            existing_lines = len(existing_content.split('\n'))
            if existing_content and not existing_content.endswith('\n'):
                existing_lines += 1
            
            # Build new file content
            final_content = "\n".join(use_stmt)
            if use_stmt:
                final_content += "\n\n"
            final_content += existing_content
            if existing_content:
                final_content += "\n\n"
            final_content += code_content
            
            # Calculate line number range in the final file
            start_line = len(use_stmt) + (1 if use_stmt else 0) + existing_lines + (1 if existing_content else 0) + 1
            end_line = start_line + len(code_stmt) - 1
            rust_code_range = (start_line, end_line)
            
            # Write to file
            final_cont_list = [line for line in final_content.split('\n') if line.strip()]
            with open(rust_code_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(final_cont_list))
        
        # Execute code writing
        code_write(trans_rust_path, trans_rust_code)
        
        return written_rust_code, rust_code_range


    def toml_write(self, toml_depend):
        CargoPath = os.path.join(self.args.trans_project_path, self.args.source_project_name, "Cargo.toml")
        if toml_depend:
            # Read existing Cargo.toml
            existing_toml = ""
            if os.path.exists(CargoPath):
                with open(CargoPath, 'r', encoding='utf-8') as f:
                    existing_toml = f.read()
            
            # Find the [dependencies] section
            if "[dependencies]" not in existing_toml:
                existing_toml += "\n[dependencies]\n"
            
            # Add new dependencies if they don't exist
            for dep in toml_depend.split('\n'):
                dep = dep.strip()
                if dep and dep not in existing_toml:
                    # Find the position after [dependencies]
                    deps_pos = existing_toml.find("[dependencies]") + len("[dependencies]")
                    # Insert new dependency
                    existing_toml = existing_toml[:deps_pos] + f"\n{dep}" + existing_toml[deps_pos:]
            
            # Write back to Cargo.toml
            with open(CargoPath, 'w', encoding='utf-8') as f:
                f.write(existing_toml)

    def call_graph_load(self, relationships_path, entities_path) -> dict:
        with open(entities_path, 'r', encoding='utf-8') as f:
            entities_list = json.load(f)
        with open(relationships_path, 'r', encoding='utf-8') as f:
            relationships_list = json.load(f)
        call_graph_dict = defaultdict(list)
        for entity in tqdm(entities_list):
            call_graph = defaultdict(list)
            if "SYSTEM" in entity['is_system']: continue
            source_unique_name = entity['unique_name']
            
            all_dependencies = []
            for relationship in relationships_list:
                if relationship['source_unique_name'] == source_unique_name:
                    target_unique_name = relationship['target_unique_name']
                    for dep_entity in entities_list:
                        if dep_entity['unique_name'] == target_unique_name and "LOCAL" in dep_entity['is_system']:
                            all_dependencies.append(dep_entity['unique_name'])
            
            code_path = os.path.join(self.args.source_project_path+"_expanded_dealed", entity['source_file'])
            with open(code_path, 'r', encoding='utf-8') as f:
                code_lists = f.read().split('\n')

            start_line = int(entity['line_begin']) -1
            end_line = int(entity['line_end'])
            code =  '\n'.join(code_lists[start_line:end_line])
            
            call_graph["source_code"] = code
            call_graph["source_type"] = entity['type']
            call_graph["source_called_name"] = all_dependencies
            call_graph["source_unique_name"] = source_unique_name
            call_graph["source_file"] = entity['source_file']

            call_graph_dict[source_unique_name] = call_graph
            
        return call_graph_dict
            
    def rust_depend_load(self, rust_depend_metas, trans_rust_code, trans_path):
        meta_depend_dict = {}
        for meta in rust_depend_metas:
            if meta['trans_rust_path'] == trans_path: continue # If the current translated rust code and the called rust code are in the same file
            if meta['trans_rust_path'] in meta_depend_dict:
                # If the path already exists, append the new context to the existing content
                meta_depend_dict[meta['trans_rust_path']] += "\n" + meta['trans_rust_code_context']
            else:
                # If the path does not exist, add directly
                meta_depend_dict[meta['trans_rust_path']] = meta['trans_rust_code_context']

        def _extract_import_code(rust_file_content):
            import_lines = []
            for line in rust_file_content.split('\n'):
                line = line.strip()
                # Match use statements, mod declarations or extern crate
                if line.startswith(('use ', 'mod ', 'extern crate ')) or \
                    (line.startswith('pub ') and ('mod ' in line or 'use ' in line)):
                    import_lines.append(line)
                # If the first non-import, non-empty line is encountered, it can be assumed that the import part ends
                elif line and not line.startswith('//') and not line.startswith('#'):
                    break
            return import_lines
        
        # Note: Here we need to keep the consistency of the key in meta_depend_dict
        for path in list(meta_depend_dict.keys()): 
            rust_path = os.path.join(self.rust_project_path, path)
            if os.path.exists(rust_path):
                with open(rust_path, 'r', encoding='utf-8') as f:
                    rust_file_content = f.read()
                import_lines = _extract_import_code(rust_file_content)
                if import_lines:
                    imports_text = '\n'.join(import_lines)
                    meta_depend_dict[path] = imports_text + '\n\n' + meta_depend_dict[path]
        
        trans_rust_dict = {}
        trans_rust_dict[trans_path] = trans_rust_code
        trans_rust_path = os.path.join(self.rust_project_path, trans_path)
        if os.path.exists(trans_rust_path):
            with open(trans_rust_path, 'r', encoding='utf-8') as f:
                trans_rust_content = f.read()
            trans_import_lines = _extract_import_code(trans_rust_content)
            if trans_import_lines:
                trans_import_text = '\n'.join(trans_import_lines)
                trans_rust_dict[trans_path] = trans_import_text + '\n\n' + trans_rust_code
        
        # Format output
        formatted_depend_context = ""
        for path, code in meta_depend_dict.items():
            formatted_depend_context += f"// path: {path}\n{code}\n\n"
        
        formatted_trans_context = ""
        for path, code in trans_rust_dict.items():
            formatted_trans_context += f"// path: {path}\n{code}\n\n"
        
        return formatted_depend_context, formatted_trans_context
                
    def free_annotation(self, source_c_code, free_function_list):
        
        # Split code into lines
        lines = source_c_code.split('\n')
        annotated_lines = []
        patterns = [re.compile(r'{}[\s]*\('.format(re.escape(func_name))) for func_name in free_function_list]
        free_pattern = re.compile(r'\b\w*free\w*[\s]*\(|\bfree\b')
        
        for line in lines:
            annotated_lines.append(line)
            should_annotate = False
            for pattern in patterns:
                if pattern.search(line):
                    should_annotate = True
                    break

            if not should_annotate and free_pattern.search(line):
                should_annotate = True
            
            if should_annotate:
                if '//' not in line:
                    annotated_lines[-1] = line + " // NOTE: Memory Deallocation Operation, NEED TO REMOVE"
                else:
                    comment_pos = line.find('//')
                    annotated_lines[-1] = (line[:comment_pos] + "// NOTE: Memory Deallocation Operation, NEED TO REMOVE" + 
                                        line[comment_pos:])
        
        return '\n'.join(annotated_lines)
    
    def create_project_structure(self, tree_str, base_path):
        lines = [
            line.rstrip()
            for line in tree_str.strip().split('\n')
            if line.strip()
            and not line.strip().startswith('```')
            and not line.strip().startswith('#')
        ]
        if not lines:
            return
        
        project_name = self.args.source_project_name
        project_path = os.path.join(base_path, project_name)

        def ensure_cargo_toml():
            cargo_toml_path = os.path.join(project_path, 'Cargo.toml')
            should_write = not os.path.exists(cargo_toml_path)
            if not should_write and tomllib is not None:
                try:
                    with open(cargo_toml_path, 'rb') as f:
                        tomllib.load(f)
                except Exception:
                    should_write = True
            if should_write:
                with open(cargo_toml_path, 'w') as f:
                    f.write(f'''[package]
name = "{project_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
''')

        if os.path.exists(project_path):
            logger.info(f"Project directory already exists: {project_path}")
            ensure_cargo_toml()
            self.normalize_rust_project_skeleton(project_path)
            return project_path
    
        os.makedirs(project_path, exist_ok=True)
        ensure_cargo_toml()
        
        current_path = project_path
        path_stack = []
        indent_stack = [-1] 
        
        for i in range(1, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
                
            # Calculate indentation level (count spaces before content)
            indent = 0
            for char in line:
                if char in ['├', '└', '│', '─', ' ']:
                    indent += 1
                else:
                    break
            
            # Extract the actual name (remove tree symbols)
            name = line.strip().lstrip('├└│─ ')
            if name == project_name:
                continue
            
            # Determine if this is a file or directory
            is_file = '.' in name and not name.endswith('/')
            
            # Adjust the path stack based on indentation
            while path_stack and indent <= indent_stack[-1]:
                path_stack.pop()
                indent_stack.pop()
            
            # Calculate the current path
            if path_stack:
                current_path = path_stack[-1]
            else:
                current_path = project_path
            
            # Create file or directory
            full_path = os.path.join(current_path, name)
            if is_file:
                if name == 'Cargo.toml':
                    with open(full_path, 'w') as f:
                        f.write(f'''[package]
name = "{project_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
''')
                # logger.info(f"Created Cargo.toml with basic configuration: {full_path}")
                elif name == 'lib.rs':
                    with open(full_path, 'w') as f:
                        f.write('''// This is a placeholder for your Rust library code''')
                else:
                    if "common" not in full_path and "main.rs" not in full_path:   
                        with open(full_path, 'w') as f:
                            f.write('''use crate::*;''')
                    else:
                        with open(full_path, 'w') as f:
                            pass
            else:
                # Create directory
                os.makedirs(full_path, exist_ok=True)
                path_stack.append(full_path)
                indent_stack.append(indent)

        self.normalize_rust_project_skeleton(project_path)
                
 
        
        pathList = [args.source_project_name]
        self.obtain_project_tree(pathList, project_path)
        return "\n".join(pathList)


    def obtain_project_tree(self, pathList, root_path, indent=""):        
        entries = os.listdir(root_path)
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
            
    # According to the given line number, find the Rust code item (item) where the line is located and return the corresponding code content.
    def get_rust_code_by_line_number(self, rust_path, line_number):
        with open(rust_path, 'r', encoding='utf-8') as f:
            rust_code_lines = f.readlines()
            rust_code = ''.join(rust_code_lines)
            
        items = self.rust_parser.find_rust_items(rust_code)
        # Find the code item containing the given line number
        for item in items:
            if item['start_line'] <= line_number <= item['end_line']:
                item_code = ''.join(rust_code_lines[item['start_line']-1:item['end_line']])
                return item_code, (item['start_line'], item['end_line'])
        return "",""
        

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    
    # Basic settings
    parser.add_argument('--model_name', type=str, default="gpt-4o-2024-11-20")
    parser.add_argument('--model_path', type=str, default="", help="model path")
    parser.add_argument('--max_new_tokens', type=int, default=5214, help="maximum number of tokens generated per LLM call")
    parser.add_argument('--temperature', type=float, default=0.1, help="LLM sampling temperature")
    parser.add_argument('--device_map', type=str, default="auto", help="device placement for local HuggingFace models")
    parser.add_argument('--local_dtype', type=str, default="auto", choices=["auto", "float16", "bfloat16", "float32"], help="torch dtype for local HuggingFace models")
    parser.add_argument('--trust_remote_code', action="store_true", help="allow custom HuggingFace model code for local models")
    parser.add_argument('--require_cuda', action="store_true", help="fail fast if the local model is not loaded on CUDA")
    
    # File path settings
    parser.add_argument("--root_dir", default="../Code_Package", type=str, help="the root path of the project")
    
    parser.add_argument('--source_project_name', default=None, help="source project name") # quadtree-0.1.0, avl
    parser.add_argument("--source_project_path", default=None, type=str, help="source project path")
    parser.add_argument("--parsed_project_path", default=None, type=str, help="source project path")
    parser.add_argument("--trans_project_path", default=None, type=str, help="source project path")
    
    # Translation settings
    parser.add_argument("--translate_mode", default="Trans_not_RA", type=str, choices=["LLM_only", "Trans_PA","Trans_not_PU","Trans_not_RA"], help="Translation mode; PA is program analysis")
    
    args = parser.parse_args()
    
    args.parsed_project_path = os.path.join(args.root_dir, "dataset/parsed_projects")
    
    now = datetime.now()
    current_time = now.strftime("%y%m%d_%H%M%S")
    args.current_time = current_time
    args.current_time = args.model_name.replace('/', '_').replace('-', '_') + '_' + args.current_time
    logger.info(f'Current Time: {args.current_time}')

    dir_name = os.path.join(args.root_dir, "dataset/crown_dataset")
    project_names = os.listdir(dir_name)
    project_name_list = [os.path.join("crown_dataset", project_name) for project_name in project_names]


    # project_list = ['crown_dataset/avl','crown_dataset/buffer','crown_dataset/genann','crown_dataset/quadtree', 'crown_dataset/rgba',
    #                 'crown_dataset/urlparser','crown_dataset/ht','crown_dataset/bst','crown_dataset/json_h','crown_dataset/libtree']

    project_list = ['crown_dataset/json_h']

    for project_name in project_list:
        print("Deal: ", project_name)
        args.source_project_path = os.path.join(args.root_dir, "dataset", project_name)
        args.source_project_name = os.path.basename(project_name)
        if "LLM_only" in args.translate_mode:
            args.trans_project_path = os.path.join(args.root_dir, "dataset/trans_projects")
            instance = Main(args)
            instance.trans_LLM_only()
        elif "Trans_PA" in args.translate_mode:
            args.trans_project_path = os.path.join(args.root_dir, "dataset/PA_trans_projects")
            instance = Main(args)
            instance.trans_PA()

        elif "Trans_not_PU" in args.translate_mode:
            args.trans_project_path = os.path.join(args.root_dir, "dataset/Trans_not_PU")
            instance = Main(args)
            instance.trans_PA()

        elif "Trans_not_RA" in args.translate_mode:
            args.trans_project_path = os.path.join(args.root_dir, "dataset/Trans_not_RA")
            instance = Main(args)
            instance.trans_PA()
        
        
        
