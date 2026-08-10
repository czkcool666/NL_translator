#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
import json
import logging
from tqdm import tqdm
import subprocess
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DoxygenXmlParser:
    def __init__(self, xml_dir, entities_path, relationships_path, project_dir):
        self.xml_dir = xml_dir
        self.project_dir = project_dir
        self.entities_path = entities_path
        self.relationships_path = relationships_path
        
    def start_parse(self):
        logger.info(f"Start to parse the xml directory: {self.xml_dir}")
        
        # Extract `entity` from the index.
        self._extract_entities_from_index()
        
        self._extract_relationships_from_xml()

    
    # extract `entify` from the index
    def _extract_entities_from_index(self):
        Entity_list = []
        
        typedef_struct_union_list = []
        
        index_path = os.path.join(self.xml_dir, 'index.xml')
        if not os.path.exists(index_path):
            raise FileNotFoundError(f"Warning: index.xml file not found")
        
        tree = ET.parse(index_path)
        root = tree.getroot()
        
        compound_list = root.findall(".//compound")
        for compound in tqdm(compound_list):
            # logger.info(f"Processing compound: {compound.get('refid')}")
            compound_name = compound.find('name').text
            compound_kind = compound.get('kind')
            compound_id = compound.get('refid')
            
                        

            
            xml_file_path = os.path.join(self.xml_dir, f"{compound_id}.xml") # obtain the defined .xml
            sub_tree = ET.parse(xml_file_path)
            sub_root = sub_tree.getroot()
  
               
            if compound_kind in ['struct', 'union']:

                # Find the specific compounddef node with matching ID
                compounddef = sub_root.find(f".//compounddef[@id='{compound_id}']")
                assert compounddef is not None, f"Warning: compounddef not found for {compound_id}"
                location = compounddef.find('location') # obtain the location tag from the xml file
                
                if location is not None:
                    file_path = location.get('bodyfile')
                    line_begin = int(location.get('line'))
                    if file_path != location.get('file'):
                        raise ValueError(f"Warning: struct/union bodyfile != current_file for {compound_id}")
                                        
                    line_number = self._complete_code_line(file_path, line_begin)
                    if line_number == line_begin:
                        line_end_temp = int(location.get('bodyend', line_begin))
                        line_end = line_end_temp if line_end_temp != -1 else line_begin
                    else:
                        line_end = line_number

                # merge all the member variable ids to the struct_union_ids
                member_id = compound_id
                for member in compound.findall('member'):
                    member_id = member_id + "#" + member.get('refid')
                is_system_tag = self._is_system_tag(os.path.join(self.project_dir, file_path), line_begin)
                
                real_file_path = os.path.basename(is_system_tag.split(":")[1].strip().strip("]"))
                
                source_code = self._extract_source_code(os.path.join(self.project_dir, file_path), line_begin, line_end)
                Entity_list.append({
                    'id': member_id,
                    'name': compound_name,
                    'unique_name': f"{compound_name}#{real_file_path}#{line_begin}",
                    'type': compound_kind,
                    'source_file': file_path,
                    'line_begin': line_begin,
                    'line_end': line_end,
                    'xml_path': compound_id,
                    'is_system': is_system_tag,
                    'source_code': source_code,
                })

            
            elif compound_kind == 'file' and (compound_name.endswith('.h') or compound_name.endswith('.c')):
                compounddef = sub_root.find(f".//compounddef[@id='{compound_id}']") # 
                
                # obtain all the `sectiondef` from the .xml file
                for sectiondef in compounddef.findall('.//sectiondef'):
                    # obtain all `member` from `sectiondef`
                     for member in sectiondef.findall('.//memberdef'):
                        member_name = member.find('name').text
                        member_id = member.get('id')
                        member_kind = member.get('kind')
                        
 
                        location = member.find('location')
                        if location is None: 
                            logger.warning(f"Warning: location not found for {member_id}")
                            continue
                        
                        # obtain the line_begin and line_end of the code
                        bodyfile = location.get('bodyfile')
                        file_file = location.get('file')
                        if bodyfile:
                            if bodyfile != file_file: # remove the `declaration`
                                logger.warning(f"Warning: file bodyfile != current_file for {member_id}")
                                continue
                            file_path = bodyfile
                            line_begin = int(location.get('line'))
                        else:
                            file_path = file_file
                            line_begin = int(location.get('line'))
                        line_number = self._complete_code_line(file_path, line_begin)
                        if line_number == line_begin:
                            line_end_temp = int(location.get('bodyend', line_begin))
                            line_end = line_end_temp if line_end_temp != -1 else line_begin
                        else:
                            line_end = line_number
                                        
                                        
                                                        
                        if member_kind == 'enum':                            
                            # Get all enumvalue nodes and their IDs
                            enum_values = member.findall('.//enumvalue')
                            for enum_value in enum_values:
                                enum_value_id = enum_value.get('id')
                                member_id = member_id + "#" + enum_value_id
                        elif member_kind == 'enumvalue':
                            continue
                        
                        elif member_kind == "typedef": 
                            if location.get('bodystart'):
                                line_begin = int(location.get('bodystart'))
                                line_end_temp = int(location.get('bodyend', line_begin))
                                line_end = line_end_temp if line_end_temp != -1 else line_begin
                        
                        
                            
                        is_system_tag = self._is_system_tag(os.path.join(self.project_dir, file_path), line_begin)
                        real_file_path = os.path.basename(is_system_tag.split(":")[1].strip().strip("]"))
                        
                        source_code = self._extract_source_code(os.path.join(self.project_dir, file_path), line_begin, line_end)
                        Entity_list.append({
                            'id': member_id,
                            'name': member_name,
                            'unique_name': f"{member_name}#{real_file_path}#{line_begin}",
                            'type': member_kind,
                            'source_file': file_path,
                            'line_begin': line_begin,
                            'line_end': line_end,
                            'xml_path': compound_id,
                            'source_code': source_code,
                            'is_system': is_system_tag,
                        })
                        
            else:
                continue
    
    
        # Filter entities in Entity_list based on their line ranges.
        Entity_list_merged_by_line = self._merge_entities_by_line(Entity_list)
        self.entities = self._merge_entities_by_source_code(Entity_list_merged_by_line)
        
        for typedef_struct_union in typedef_struct_union_list:
            source_id = typedef_struct_union.get("source_id")
            target_id = typedef_struct_union.get("target_id")
            
            for entity in self.entities:
                if target_id in entity.get("id") and source_id not in entity.get("id"):
                    entity["id"] = f"{entity.get('id')}#{source_id}"
                    break
                    
        
        # After processing all compounds, save entities to JSON file
        with open(self.entities_path, 'w', encoding='utf-8') as f:
            json.dump(self.entities, f, indent=2, ensure_ascii=False)            
        logger.info(f"Successfully parsed index.xml. Found {len(self.entities)} entities, saved to {os.path.basename(self.entities_path)}")

    def _extract_source_code(self, code_path, line_begin, line_end):
        with open(code_path, 'r', encoding='utf-8') as f:
            code_lists = f.read().split('\n')

        start_line = int(line_begin) -1
        end_line = int(line_end)
        code =  '\n'.join(code_lists[start_line:end_line])
        return code
    


    def _complete_code_line(self, code_path, line_begin):
        code_file_path = os.path.join(self.project_dir, code_path)

        with open(code_file_path, 'r', encoding='utf-8') as f:
            code_lines = f.readlines()
            
        if line_begin <= 0 or line_begin > len(code_lines):
            logger.warning(f"Invalid line number {line_begin} for file {code_file_path}")
            return line_begin
        
        current_line = line_begin  # Keep as 1-based
        first_line = code_lines[current_line - 1].rstrip()  # Remove trailing whitespace
        
        # Case 1: Line ends with backslash
        if first_line.endswith('\\'): 
            while current_line <= len(code_lines):
                line = code_lines[current_line - 1].rstrip()
                if not line.endswith('\\'):
                    return current_line
                current_line += 1
            return current_line - 1  # Reached end of file
        
        # Case 2: Line ends with '{'
        elif first_line.endswith('{'):
            left_braces, right_braces = self._count_braces_safely(first_line)
            brace_count = left_braces - right_braces
            current_line += 1
            
            while current_line <= len(code_lines):
                line = code_lines[current_line - 1].strip()
                left_braces, right_braces = self._count_braces_safely(line)
                brace_count += left_braces - right_braces
                
                # If all braces are matched, we found the end
                if brace_count == 0:
                    return current_line
                
                current_line += 1
            
            logger.warning(f"Unclosed brace block starting at line {line_begin} in {code_path}")
            return line_begin

        return line_begin
    

    def _count_braces_safely(self, line):
        left_braces = 0
        right_braces = 0
        i = 0
        in_string = False
        in_char = False
        in_single_comment = False
        in_multi_comment = False
        string_delimiter = None
        
        while i < len(line):
            char = line[i]

            if not in_string and not in_char and not in_single_comment:
                if i < len(line) - 1 and line[i:i+2] == '/*':
                    in_multi_comment = True
                    i += 2
                    continue
                elif i < len(line) - 1 and line[i:i+2] == '*/' and in_multi_comment:
                    in_multi_comment = False
                    i += 2
                    continue

            if not in_string and not in_char and not in_multi_comment:
                if i < len(line) - 1 and line[i:i+2] == '//':
                    in_single_comment = True
                    i += 2
                    continue

            if in_single_comment or in_multi_comment:
                i += 1
                continue
                
            if char == '\\' and (in_string or in_char):
                i += 2  
                continue

            if not in_char and char in ['"', "'"]:
                if not in_string:
                    in_string = True
                    string_delimiter = char
                elif char == string_delimiter:
                    in_string = False
                    string_delimiter = None
                i += 1
                continue
            
            if not in_string and char == "'":
                if not in_char:
                    in_char = True
                else:
                    in_char = False
                i += 1
                continue
            
            if not in_string and not in_char and not in_single_comment and not in_multi_comment:
                if char == '{':
                    left_braces += 1
                elif char == '}':
                    right_braces += 1
                    
            i += 1
            
        return left_braces, right_braces




    def _merge_entities_by_line(self, Entity_list):
        file_groups = {}
        for i, entity in enumerate(Entity_list):
            source_file = entity.get('source_file')
            if source_file not in file_groups:
                file_groups[source_file] = []
            file_groups[source_file].append((i, entity))
        
        entities_to_remove = set()
        
        for source_file, entities in file_groups.items():
            for i, (idx1, e1) in enumerate(entities):
                e1_begin = int(e1.get('line_begin', 0))
                e1_end = int(e1.get('line_end', 0))
                
                for j, (idx2, e2) in enumerate(entities):
                    if idx1 == idx2:  # Skip self comparison
                        continue
                    
                    e2_begin = int(e2.get('line_begin', 0))
                    e2_end = int(e2.get('line_end', 0))
                
                    if (e1_begin <= e2_begin and e2_end <= e1_end and
                        not (e1_begin == e2_begin and e1_end == e2_end)):
                        
                        entities_to_remove.add(idx2)
                        print(f"Entity will be removed - file: {source_file}")
                        print(f"  Parent entity: {e1.get('name')} (id: {e1.get('id')}, line: {e1_begin}-{e1_end})")
                        print(f"  Removed entity: {e2.get('name')} (id: {e2.get('id')}, line: {e2_begin}-{e2_end})")
                        
                        e2_id = e2.get('id', '')
                        e1_id = e1.get('id', '')
                        if e2_id and e2_id not in e1_id.split('#'):
                            e1['id'] = f"{e1_id}#{e2_id}"
        
        filtered_list = [entity for i, entity in enumerate(Entity_list) if i not in entities_to_remove]
        return filtered_list

    def _merge_entities_by_source_code(self, Entity_list):
        source_code_groups = {}
        for i, entity in enumerate(Entity_list):
            source_code = entity.get('source_code', '').strip()
            if not source_code:  
                continue
            if source_code not in source_code_groups:
                source_code_groups[source_code] = []
            source_code_groups[source_code].append((i, entity))
        
        # Used to mark the entities to be removed
        entities_to_remove = set()
        
        # Process each source code group
        for source_code, entities in source_code_groups.items():
            if len(entities) > 1:  
                base_idx, base_entity = entities[0]
                merged_id = base_entity['id']

                for other_idx, other_entity in entities[1:]:
                    other_id = other_entity['id']
                    if other_id and other_id not in merged_id.split('#'):
                        merged_id = f"{merged_id}#{other_id}"
                    entities_to_remove.add(other_idx)
                
                # UpdateID
                base_entity['id'] = merged_id
    
        filtered_list = [entity for i, entity in enumerate(Entity_list) if i not in entities_to_remove]
        return filtered_list
        
    
    def _extract_relationships_from_xml(self):
        relationships = []
        partial_relationships_path = f"{self.relationships_path}.partial.jsonl"
        completed_entity_indices = set()

        if os.path.exists(partial_relationships_path):
            logger.info(f"Resuming relationships from checkpoint: {partial_relationships_path}")
            with open(partial_relationships_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        checkpoint_entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entity_index = checkpoint_entry.get('entity_index')
                    if entity_index is None:
                        continue
                    completed_entity_indices.add(entity_index)
                    relationships.extend(checkpoint_entry.get('relationships', []))

        with open(self.entities_path, 'r', encoding='utf-8') as f:
            Entity_list = json.load(f)
        
        entity_one_id = {entity.get('id') for entity in Entity_list if '#' not in entity.get('id')}
        id_to_unique_name = {}
        ref_to_group_ids = defaultdict(list)
        xml_roots = {}

        for entity in Entity_list:
            entity_id = entity.get('id')
            id_to_unique_name.setdefault(entity_id, entity.get('unique_name'))
            if entity_id and "#" in entity_id:
                for ref_id in entity_id.split('#'):
                    ref_to_group_ids[ref_id].append(entity_id)

        def get_xml_root(xml_path):
            if not xml_path:
                return None
            if xml_path not in xml_roots:
                xml_file_path = os.path.join(self.xml_dir, f"{xml_path}.xml")
                xml_roots[xml_path] = ET.parse(xml_file_path).getroot()
            return xml_roots[xml_path]

        remaining_entity_indices = [
            entity_index for entity_index in range(len(Entity_list))
            if entity_index not in completed_entity_indices
        ]

        with open(partial_relationships_path, 'a', encoding='utf-8') as checkpoint_file:
            for entity_index in tqdm(
                remaining_entity_indices,
                total=len(Entity_list),
                initial=len(completed_entity_indices),
                desc="Processing Relationships"
            ):
                entity = Entity_list[entity_index]
                entity_relationships = []
                
                entity_id = entity.get('id') # concat by `#`
                source_entity_ids = entity_id.split('#')
                
                            
                entity_source_file = entity.get('source_file')
                xml_path = entity.get('xml_path')
                entity_line_begin = entity.get('line_begin')
                entity_line_end = entity.get('line_end')
                
                if entity.get('type') in ['struct', 'union']:
                    root = get_xml_root(xml_path)
                    if root is None:
                        checkpoint_entry = {'entity_index': entity_index, 'relationships': []}
                        checkpoint_file.write(json.dumps(checkpoint_entry, ensure_ascii=False) + '\n')
                        checkpoint_file.flush()
                        continue
                    includes = root.find('.//includes')
                    if includes is not None and includes.get('refid'):
                        xml_path = includes.get('refid')
                
                root = get_xml_root(xml_path)
                if root is None:
                    checkpoint_entry = {'entity_index': entity_index, 'relationships': []}
                    checkpoint_file.write(json.dumps(checkpoint_entry, ensure_ascii=False) + '\n')
                    checkpoint_file.flush()
                    continue
                refs_codelines_list = self._extract_refs_from_codelines(root, entity_line_begin, entity_line_end)
                if entity.get('type') in ['variable']:
                    refs_memberdef_list = []
                else:
                    refs_memberdef_list = self._extract_refs_from_memberdef(root, entity_id, xml_path, get_xml_root)
                    
                refs_list = list(set(refs_codelines_list + refs_memberdef_list))
                
                call_refs_list = [ref for ref in refs_list if ref not in source_entity_ids]
                # Build `reference` relation. `reference` means A use|call B
                for ref in call_refs_list:
                    if ref in entity_one_id:
                        entity_relationships.append({
                            'source': entity_id,
                            'target': ref,
                            'source_unique_name': entity.get('unique_name'),
                            'target_unique_name': id_to_unique_name[ref],
                            'type': 'reference'
                        })
                    else:
                        matching_groups = ref_to_group_ids.get(ref, [])
                        for entity_group in matching_groups:
                            entity_relationships.append({
                                'source': entity_id,
                                'target': entity_group, # ref is the sub_id of entity_group
                                'source_unique_name': entity.get('unique_name'),
                                'target_unique_name': id_to_unique_name[entity_group],
                                'type': 'reference'
                            })
                relationships.extend(entity_relationships)
                checkpoint_entry = {'entity_index': entity_index, 'relationships': entity_relationships}
                checkpoint_file.write(json.dumps(checkpoint_entry, ensure_ascii=False) + '\n')
                checkpoint_file.flush()
        
        unique_relationships = [dict(t) for t in {tuple(d.items()) for d in relationships}]
        # After processing all compounds, save entities to JSON file
        with open(self.relationships_path, 'w', encoding='utf-8') as f:
            json.dump(unique_relationships, f, indent=2, ensure_ascii=False)            
        if os.path.exists(partial_relationships_path):
            os.remove(partial_relationships_path)
        logger.info(f"Successfully parsed index.xml. Found {len(relationships)} relationships, saved to {os.path.basename(self.relationships_path)}")
          

    def _extract_refs_from_codelines(self, root, line_begin, line_end):
        refs = []
        
        # First find all codeline nodes
        codelines = root.findall('.//codeline')
        # codelines = root.findall('.//{*}codeline')
        # Filter codelines within the target range
        target_codelines = [
            codeline for codeline in codelines
            if line_begin <= int(codeline.get('lineno', 0)) <= line_end
        ]

        # Process the filtered codelines
        for codeline in target_codelines:
            # Get refid from the codeline itself
            codeline_refid = codeline.get('refid')
            if codeline_refid:
                refs.append(codeline_refid)
            
            # Get refids from all ref elements within this codeline
            for ref in codeline.findall('.//ref'):
                refid = ref.get('refid')
                if refid:
                    refs.append(refid)
        
        return list(set(refs))  # Remove duplicates

    def _extract_refs_from_memberdef(self, root, entity_ids, xml_path, get_xml_root=None):
        refs = []
        for entity_id in entity_ids.split('#'):
            memberdef = root.find(f".//memberdef[@id='{entity_id}']")
            if memberdef is not None:
                name_element = memberdef.find('name')
                if name_element is not None:
                    member_name =  name_element.text
                # find all the `ref refid` and `references refid` from the `memberdef`
                ref_list = memberdef.findall('.//ref')
                references_list = memberdef.findall('.//references')
                
                # DEBUG: referencedby_list records referenced items
                referencedby_list = memberdef.findall('.//referencedby')
                for ref in ref_list:
                    refid = ref.get('refid')
                    if refid:
                        refs.append(refid)
                        
                # DEBUG: If the compoundref item of the references item is not consistent with the current xml file, extract it again related relations // supplement missing function relations
                for ref in references_list:
                    refs_xml_path = ref.get('compoundref') 
                    refid = ref.get('refid')
                    if not refid: continue
                    if refs_xml_path is not None and refs_xml_path != xml_path and not refid.startswith("struct") and not refid.startswith("union"):
                        ref_name = ref.text
                        refs_root = get_xml_root(refs_xml_path) if get_xml_root else ET.parse(os.path.join(self.xml_dir, f"{refs_xml_path}.xml")).getroot()
                        if refs_root is None:
                            continue
                        refs += self._extract_refs_from_references(refs_root, ref_name)
                    else:
                        refs.append(refid)
                             
                for ref in referencedby_list:
                    refby_xml_path = ref.get('compoundref')
                    startline = ref.get('startline')
                    endline = ref.get('endline')
                    if not refby_xml_path or not startline or not endline:
                        continue
                    try:
                        startline_int = int(startline)
                        endline_int = int(endline)
                    except ValueError:
                        continue
                    entity_ids_p = "_"+entity_ids.split("_")[-1]
                    refby_root = get_xml_root(refby_xml_path) if get_xml_root else ET.parse(os.path.join(self.xml_dir, f"{refby_xml_path}.xml")).getroot()
                    if refby_root is None:
                        continue
                    refs_from_referencedby = self._extract_refs_from_referencedby(refby_root, entity_ids_p, startline_int, endline_int)   #function error
                    if refs_from_referencedby:
                        refs += refs_from_referencedby
        
        return list(set(refs))


    def _extract_refs_from_references(self, root, name):
        refsid = []
        for memberdef in root.findall('.//memberdef'):
            name_element = memberdef.find('name')
            if name_element is not None and name_element.text==name:
                refid = memberdef.get('id')
                if refid:
                    refsid.append(refid)
        return refsid
    

    def _extract_refs_from_referencedby(self, root, entity_ids_p, line_begin, line_end):
        refs = []
        # First find all codeline nodes
        codelines = root.findall('.//codeline')
        # Filter codelines within the target range
        target_codelines = [
            codeline for codeline in codelines
            if line_begin <= int(codeline.get('lineno', 0)) <= line_end
        ]

        # Process the filtered codelines
        for codeline in target_codelines:
            # Check if this line contains the target entity ID
            codeline_xml_str = ET.tostring(codeline, encoding='unicode')
            if entity_ids_p not in codeline_xml_str:
                continue
            
            # Find the ref element containing the target entity ID
            target_ref = None
            for ref in codeline.findall('.//ref'):
                refid = ref.get('refid', '')
                if entity_ids_p in refid:
                    target_ref = ref
                    break
            
            if target_ref is None:
                continue
                
            codeline_text = ''.join(codeline.itertext())
            
            target_function_name = target_ref.text.strip() if target_ref.text else ""
            
            func_pos = codeline_text.find(target_function_name)
            if func_pos == -1:
                continue
                
            text_after_func = codeline_text[func_pos + len(target_function_name):]
            left_paren_pos = text_after_func[:2].find('(') if len(text_after_func) >= 1 and '(' in text_after_func[:2] else -1
            if left_paren_pos == -1:
                continue
                
            paren_count = 0
            right_paren_pos = -1
            for i, char in enumerate(text_after_func[left_paren_pos:], left_paren_pos):
                if char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
                    if paren_count == 0:
                        right_paren_pos = i
                        break
            
            if right_paren_pos == -1:
                continue
                
            params_start = func_pos + len(target_function_name) + left_paren_pos + 1
            params_end = func_pos + len(target_function_name) + right_paren_pos
            params_text = codeline_text[params_start:params_end]
            
            all_refs = codeline.findall('.//ref')

            for ref in all_refs:
                ref_text = ref.text.strip() if ref.text else ""
                refid = ref.get('refid', '')
                
                if entity_ids_p in refid:
                    continue
                if ref_text and ref_text in params_text:
                    refs.append(refid)
        
        return list(set(refs))  


    def _is_system_tag(self, code_file_path, code_line):
        with open(code_file_path, 'r', encoding='utf-8') as f:
            code_cont_list = f.readlines()
            
        adjusted_line = code_line - 1
        
        for i in range(adjusted_line, -1, -1):
            line = code_cont_list[i]
            if line.strip().startswith("//"):
                if "LOCAL:" in line:
                    return line
                elif "SYSTEM:" in line:
                    return line
        return "LOCAL:"
    
    
def setup_doxygen(project_path, project_name):
    """Set up doxygen environment in the project directory"""
    import shutil
    import subprocess
    
    # Get the path of the Doxyfile template
    script_dir = os.path.dirname(os.path.abspath(__file__))
    doxyfile_template = os.path.join(script_dir, 'Doxyfile')

    if not os.path.exists(doxyfile_template):
        raise FileNotFoundError(f"Doxyfile template not found at: {doxyfile_template}")
    
    with open(doxyfile_template, 'r', encoding='utf-8') as f:
        doxyfile_content = f.read()
    new_doxyfile_content = doxyfile_content.replace('##PROJECT_NAME##',project_name) \
                                            .replace('##INPUT##', project_path)
    # Change to project directory and run doxygen
    original_dir = os.getcwd()
    try:
        os.chdir(project_path)
        subprocess.run(['doxygen', '-g', 'Doxyfile'], check=True)
        with open('Doxyfile', 'w', encoding='utf-8') as f:
            f.write(new_doxyfile_content)
        subprocess.run(['doxygen', 'Doxyfile'], check=True)
    finally:
        os.chdir(original_dir)
    
    return os.path.join(project_path, 'doxygen_output', 'xml')

        
        
