import os
from tree_sitter import Language, Parser

class CParser:

    def __init__(self, root_path: str) -> None:
        self.root_path = root_path
        self.c_parser_so_path = os.path.join(root_path, "dependencyLib/c_parser_new.so")
        self.C_LANGUAGE = Language(self.c_parser_so_path, 'c')
        self.parser = Parser()
        self.parser.set_language(self.C_LANGUAGE)

    def _find_declarator_name(self,node) -> str | None:
        if node.type in ['field_identifier', 'identifier']:
            return node.text.decode('utf8')
        for child in node.children:
            found_name = self._find_declarator_name(child)
            if found_name:
                return found_name
        return None


    def get_c_member_name_by_index(self,declaration_code: str, member_index: int) -> str | None:
        tree = self.parser.parse(bytes(declaration_code, "utf8"))
        
        query_string = """
        [
        (struct_specifier body: (field_declaration_list) @body)
        (type_definition type: (struct_specifier body: (field_declaration_list) @body))
        
        (union_specifier body: (field_declaration_list) @body)
        (type_definition type: (union_specifier body: (field_declaration_list) @body))
        
        (enum_specifier body: (enumerator_list) @body)
        (type_definition type: (enum_specifier body: (enumerator_list) @body))
        ]
        """
        query = self.C_LANGUAGE.query(query_string)
        captures = query.captures(tree.root_node)

        target_body_node = None
        for node, capture_name in captures:
            if capture_name == 'body':
                target_body_node = node
                break
                
        if not target_body_node:
            print(f"Warning: Could not find a struct/union/enum body in the provided code.")
            return None

        member_names = []
        
        if target_body_node.type == 'field_declaration_list':
            for field_node in target_body_node.children:
                if field_node.type == 'field_declaration':
                    for child in field_node.children:
                        if 'declarator' in child.type or 'identifier' in child.type:
                            member_name = self._find_declarator_name(child)
                            if member_name:
                                member_names.append(member_name)
                                

        elif target_body_node.type == 'enumerator_list':
            for enumerator_node in target_body_node.children:
                if enumerator_node.type == 'enumerator':
                    name_node = enumerator_node.child_by_field_name('name')
                    if name_node:
                        member_names.append(name_node.text.decode('utf8'))

        # Check index and return result
        if 0 <= member_index < len(member_names):
            return member_names[member_index]
        else:
            return None
