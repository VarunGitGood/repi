# tree-sitter S-expressions for Python, TypeScript, and JavaScript

PYTHON_ENTITY_QUERY = """
; Functions
(function_definition
  name: (identifier) @function.name) @function.decl

; Classes
(class_definition
  name: (identifier) @class.name) @class.decl

; Imports
(import_statement
  name: (dotted_name) @import.name) @import.decl

(import_from_statement
  module_name: (dotted_name) @import.name) @import.decl
"""

PYTHON_CALL_QUERY = """
(call
  function: [
    (identifier) @call.callee
    (attribute attribute: (identifier) @call.callee)
  ]) @call.node
"""

# TypeScript (Updated for 0.25+ compatibility)
TS_ENTITY_QUERY = """
; Functions
(function_declaration
  name: (identifier) @function.name) @function.decl

(lexical_declaration
  (variable_declarator
    name: (identifier) @function.name
    value: (arrow_function))) @function.decl

; Classes
(class_declaration
  name: (type_identifier) @class.name) @class.decl

; Methods
(method_definition
  name: (property_identifier) @method.name) @method.decl

; Interface
(interface_declaration
  name: (type_identifier) @interface.name) @interface.decl

; Type Alias
(type_alias_declaration
  name: (type_identifier) @type_alias.name) @type_alias.decl

; Enum
(enum_declaration
  name: (identifier) @enum.name) @enum.decl

; Imports
(import_statement
  source: (string) @import.name) @import.decl
"""

# JavaScript (Uses identifier instead of type_identifier)
JS_ENTITY_QUERY = """
; Functions
(function_declaration
  name: (identifier) @function.name) @function.decl

(lexical_declaration
  (variable_declarator
    name: (identifier) @function.name
    value: (arrow_function))) @function.decl

; Classes
(class_declaration
  name: (identifier) @class.name) @class.decl

; Methods
(method_definition
  name: (property_identifier) @method.name) @method.decl

; Imports
(import_statement
  source: (string) @import.name) @import.decl
"""

TS_CALL_QUERY = """
(call_expression
  function: [
    (identifier) @call.callee
    (member_expression property: (property_identifier) @call.callee)
  ]) @call.node
"""
