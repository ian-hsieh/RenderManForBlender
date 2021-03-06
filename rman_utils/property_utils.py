from . import texture_utils
from . import string_utils
from . import shadergraph_utils
from ..rfb_logger import rfb_log
from bpy.props import *
import bpy
import sys


__GAINS_TO_ENABLE__ = {
    'diffuseGain': 'enableDiffuse',
    'specularFaceColor': 'enablePrimarySpecular',
    'specularEdgeColor': 'enablePrimarySpecular',
    'roughSpecularFaceColor': 'enableRoughSpecular',
    'roughSpecularEdgeColor': 'enableRoughSpecular',
    'clearcoatFaceColor': 'enableClearCoat',
    'clearcoatEdgeColor': 'enableClearCoat',
    'iridescenceFaceGain': 'enableIridescence',
    'iridescenceEdgeGain': 'enableIridescence',
    'fuzzGain': 'enableFuzz',
    'subsurfaceGain': 'enableSubsurface',
    'singlescatterGain': 'enableSingleScatter',
    'singlescatterDirectGain': 'enableSingleScatter',
    'refractionGain': 'enableGlass',
    'reflectionGain': 'enableGlass',
    'glowGain': 'enableGlow',
}

def set_rix_param(params, param_type, param_name, val, is_reference=False, is_array=False, array_len=-1):
    if is_array:
        if param_type == 'float':
            params.SetFloatArray(param_name, val, array_len)
        elif param_type == 'int':
            params.SetIntegerArray(param_name, val, array_len)
        elif param_type == 'color':
            params.SetColorArray(param_name, val, array_len/3)
        elif param_type == 'string':
            params.SetStringArray(param_name, val, array_len)
    elif is_reference:
        if param_type == "float":
            params.ReferenceFloat(param_name, val)
        elif param_type == "int":
            params.ReferenceInteger(param_name, val)
        elif param_type == "color":
            params.ReferenceColor(param_name, val)
        elif param_type == "point":
            params.ReferencePoint(param_name, val)            
        elif param_type == "vector":
            params.ReferenceVector(param_name, val)
        elif param_type == "normal":
            params.ReferenceNormal(param_name, val) 
        elif param_type == "struct":
            params.ReferenceStruct(param_name, val)                        
    else:        
        if param_type == "float":
            params.SetFloat(param_name, float(val))
        elif param_type == "int":
            params.SetInteger(param_name, int(val))
        elif param_type == "color":
            params.SetColor(param_name, val)
        elif param_type == "string":
            params.SetString(param_name, val)
        elif param_type == "point":
            params.SetPoint(param_name, val)                            
        elif param_type == "vector":
            params.SetVector(param_name, val)
        elif param_type == "normal":
            params.SetNormal(param_name, val)   

def build_output_param_str(mat_name, from_node, from_socket, convert_socket=False):
    from_node_name = shadergraph_utils.get_node_name(from_node, mat_name)
    from_sock_name = shadergraph_utils.get_socket_name(from_node, from_socket)

    # replace with the convert node's output
    if convert_socket:
        if shadergraph_utils.is_float_type(from_socket):
            return "convert_%s.%s:resultRGB" % (from_node_name, from_sock_name)
        else:
            return "convert_%s.%s:resultF" % (from_node_name, from_sock_name)

    else:
        return "%s:%s" % (from_node_name, from_sock_name)


def get_output_param_str(node, mat_name, socket, to_socket=None):
    # if this is a node group, hook it up to the input node inside!
    if node.bl_idname == 'ShaderNodeGroup':
        ng = node.node_tree
        group_output = next((n for n in ng.nodes if n.bl_idname == 'NodeGroupOutput'),
                            None)
        if group_output is None:
            return "error:error"

        in_sock = group_output.inputs[socket.name]
        if len(in_sock.links):
            link = in_sock.links[0]
            return build_output_param_str(mat_name + '.' + node.name, link.from_node, link.from_socket, shadergraph_utils.do_convert_socket(link.from_socket, to_socket))
        else:
            return "error:error"
    if node.bl_idname == 'NodeGroupInput':
        global current_group_node

        if current_group_node is None:
            return "error:error"

        in_sock = current_group_node.inputs[socket.name]
        if len(in_sock.links):
            link = in_sock.links[0]
            return build_output_param_str(mat_name, link.from_node, link.from_socket, shadergraph_utils.do_convert_socket(link.from_socket, to_socket))
        else:
            return "error:error"

    return build_output_param_str(mat_name, node, socket, shadergraph_utils.do_convert_socket(socket, to_socket))    


def is_vstruct_or_linked(node, param):
    meta = node.prop_meta[param]

    if 'vstructmember' not in meta.keys():
        return node.inputs[param].is_linked
    elif param in node.inputs and node.inputs[param].is_linked:
        return True
    else:
        vstruct_name, vstruct_member = meta['vstructmember'].split('.')
        if node.inputs[vstruct_name].is_linked:
            from_socket = node.inputs[vstruct_name].links[0].from_socket
            vstruct_from_param = "%s_%s" % (
                from_socket.identifier, vstruct_member)
            return vstruct_conditional(from_socket.node, vstruct_from_param)
        else:
            return False

# tells if this param has a vstuct connection that is linked and
# conditional met


def is_vstruct_and_linked(node, param):
    meta = node.prop_meta[param]

    if 'vstructmember' not in meta.keys():
        return False
    else:
        vstruct_name, vstruct_member = meta['vstructmember'].split('.')
        if node.inputs[vstruct_name].is_linked:
            from_socket = node.inputs[vstruct_name].links[0].from_socket
            # if coming from a shader group hookup across that
            if from_socket.node.bl_idname == 'ShaderNodeGroup':
                ng = from_socket.node.node_tree
                group_output = next((n for n in ng.nodes if n.bl_idname == 'NodeGroupOutput'),
                                    None)
                if group_output is None:
                    return False

                in_sock = group_output.inputs[from_socket.name]
                if len(in_sock.links):
                    from_socket = in_sock.links[0].from_socket
            vstruct_from_param = "%s_%s" % (
                from_socket.identifier, vstruct_member)
            return vstruct_conditional(from_socket.node, vstruct_from_param)
        else:
            return False

# gets the value for a node walking up the vstruct chain


def get_val_vstruct(node, param):
    if param in node.inputs and node.inputs[param].is_linked:
        from_socket = node.inputs[param].links[0].from_socket
        return get_val_vstruct(from_socket.node, from_socket.identifier)
    elif is_vstruct_and_linked(node, param):
        return True
    else:
        return getattr(node, param)

# parse a vstruct conditional string and return true or false if should link


def vstruct_conditional(node, param):
    if not hasattr(node, 'shader_meta') and not hasattr(node, 'output_meta'):
        return False
    meta = getattr(
        node, 'shader_meta') if node.bl_idname == "PxrOSLPatternNode" else node.output_meta
    if param not in meta:
        return False
    meta = meta[param]
    if 'vstructConditionalExpr' not in meta.keys():
        return True

    expr = meta['vstructConditionalExpr']
    expr = expr.replace('connect if ', '')
    set_zero = False
    if ' else set 0' in expr:
        expr = expr.replace(' else set 0', '')
        set_zero = True

    tokens = expr.split()
    new_tokens = []
    i = 0
    num_tokens = len(tokens)
    while i < num_tokens:
        token = tokens[i]
        prepend, append = '', ''
        while token[0] == '(':
            token = token[1:]
            prepend += '('
        while token[-1] == ')':
            token = token[:-1]
            append += ')'

        if token == 'set':
            i += 1
            continue

        # is connected change this to node.inputs.is_linked
        if i < num_tokens - 2 and tokens[i + 1] == 'is'\
                and 'connected' in tokens[i + 2]:
            token = "is_vstruct_or_linked(node, '%s')" % token
            last_token = tokens[i + 2]
            while last_token[-1] == ')':
                last_token = last_token[:-1]
                append += ')'
            i += 3
        else:
            i += 1
        if hasattr(node, token):
            token = "get_val_vstruct(node, '%s')" % token

        new_tokens.append(prepend + token + append)

    if 'if' in new_tokens and 'else' not in new_tokens:
        new_tokens.extend(['else', 'False'])
    return eval(" ".join(new_tokens))


def generate_property(sp, update_function=None):
    options = {'ANIMATABLE'}
    param_name = sp._name #sp.attrib['name']
    renderman_name = param_name
    # blender doesn't like names with __ but we save the
    # "renderman_name with the real one"
    if param_name[0] == '_':
        param_name = param_name[1:]
    if param_name[0] == '_':
        param_name = param_name[1:]

    param_label = sp.label if hasattr(sp,'label') else param_name

    param_widget = sp.widget.lower() if hasattr(sp,'widget') and sp.widget else 'default'

    param_type = sp.type 

    prop_meta = dict()
    param_default = sp.default
    if hasattr(sp, 'vstruct') and sp.vstruct:
        param_type = 'struct'
        prop_meta['vstruct'] = True
    else:
        param_type = sp.type
    renderman_type = param_type

    if hasattr(sp, 'vstructmember'):
        prop_meta['vstructmember'] = sp.vstructmember

    if hasattr(sp, 'vstructConditionalExpr'):
        prop_meta['vstructConditionalExpr'] = sp.vstructConditionalExpr        
     
    prop = None

    # set this prop as non connectable
    if param_widget in ['null', 'checkbox', 'switch']:
        prop_meta['__noconnection'] = True

    prop_meta['widget'] = param_widget

    if hasattr(sp, 'connectable') and not sp.connectable:
        prop_meta['__noconnection'] = True


    if hasattr(sp, 'conditionalVisOps'):
        prop_meta['conditionalVisOp'] = sp.conditionalVisOps

    param_help = ''
    if hasattr(sp, 'help'):
        param_help = sp.help

    if hasattr(sp, 'riopt'):
        prop_meta['riopt'] = sp.riopt

    if hasattr(sp, 'riattr'):
        prop_meta['riattr'] = sp.riattr

    if hasattr(sp, 'primvar'):
        prop_meta['primvar'] = sp.primvar

    if hasattr(sp, 'inheritable'):
        prop_meta['inheritable'] = sp.inheritable
    
    if hasattr(sp, 'inherit_true_value'):
        prop_meta['inherit_true_value'] = sp.inherit_true_value

    if 'float' == param_type:
        if sp.is_array():
            prop = FloatVectorProperty(name=param_label,
                                       default=param_default, precision=3,
                                       size=len(param_default),
                                       description=param_help,
                                       update=update_function)
            prop_meta['arraySize'] = sp.size
        else:
            if param_widget == 'checkbox' or param_widget == 'switch':
                
                prop = BoolProperty(name=param_label,
                                    default=bool(param_default),
                                    description=param_help, update=update_function)
            elif param_widget == 'mapper':
                items = []
                for k,v in sp.options.items():
                    items.append((str(v), k, ''))
                
                bl_default = ''
                for item in items:
                    if item[0] == str(param_default):
                        bl_default = item[0]
                        break                

                prop = EnumProperty(name=param_label,
                                    items=items,
                                    default=bl_default,
                                    description=param_help, update=update_function)
            else:
                param_min = sp.min if hasattr(sp, 'min') else (-1.0 * sys.float_info.max)
                param_max = sp.max if hasattr(sp, 'max') else sys.float_info.max
                param_min = sp.slidermin if hasattr(sp, 'slidermin') else param_min
                param_max = sp.slidermax if hasattr(sp, 'slidermax') else param_max   

                prop = FloatProperty(name=param_label,
                                     default=param_default, precision=3,
                                     soft_min=param_min, soft_max=param_max,
                                     description=param_help, update=update_function)


        renderman_type = 'float'

    elif param_type == 'int' or param_type == 'integer':
        if sp.is_array(): 
            prop = IntVectorProperty(name=param_label,
                                     default=param_default,
                                     size=len(param_default),
                                     description=param_help,
                                     update=update_function)
            prop_meta['arraySize'] = sp.size                                     
        else:
            param_default = int(param_default) if param_default else 0
            # make invertT default 0
            if param_name == 'invertT':
                param_default = 0

            if param_widget == 'checkbox' or param_widget == 'switch':
                prop = BoolProperty(name=param_label,
                                    default=bool(param_default),
                                    description=param_help, update=update_function)

            elif param_widget == 'mapper':
                items = []
                for k,v in sp.options.items():
                    items.append((str(v), k, ''))
                
                bl_default = ''
                for item in items:
                    if item[0] == str(param_default):
                        bl_default = item[0]
                        break

                prop = EnumProperty(name=param_label,
                                    items=items,
                                    default=bl_default,
                                    description=param_help, update=update_function)
            else:
                pass
                param_min = int(sp.min) if hasattr(sp, 'min') else 0
                param_max = int(sp.max) if hasattr(sp, 'max') else 2 ** 31 - 1

                prop = IntProperty(name=param_label,
                                   default=param_default,
                                   soft_min=param_min,
                                   soft_max=param_max,
                                   description=param_help, update=update_function)
        renderman_type = 'int'

    elif param_type == 'color':
        if sp.is_array():
            prop_meta['arraySize'] = sp.size
            return (None, None, None)
        if param_default == 'null' or param_default is None:
            param_default = '0 0 0'
        prop = FloatVectorProperty(name=param_label,
                                   default=param_default, size=3,
                                   subtype="COLOR",
                                   soft_min=0.0, soft_max=1.0,
                                   description=param_help, update=update_function)
        renderman_type = 'color'
    elif param_type == 'shader':
        param_default = ''
        prop = StringProperty(name=param_label,
                              default=param_default,
                              description=param_help, update=update_function)
        renderman_type = 'string'
    elif param_type == 'string' or param_type == 'struct':
        if param_default is None:
            param_default = ''
        else:
            param_default = str(param_default)
        # if '__' in param_name:
        #    param_name = param_name[2:]
        if param_widget == 'fileinput' or param_widget == 'assetidinput' or (param_widget == 'default' and param_name == 'filename'):
            prop = StringProperty(name=param_label,
                                  default=param_default, subtype="FILE_PATH",
                                  description=param_help, update=update_function)
        elif param_widget == 'mapper':
            items = []
            for k,v in sp.options.items():
                items.append((str(v), k, ''))
            
            prop = EnumProperty(name=param_label,
                                default=param_default, description=param_help,
                                items=items,
                                update=update_function)

        elif param_widget == 'popup':
            items = []
            for k,v in sp.options.items():
                items.append((str(v), k, ''))
            prop = EnumProperty(name=param_label,
                                default=param_default, description=param_help,
                                items=items, update=update_function)

        elif param_widget == 'scenegraphlocation':
            reference_type = eval(sp.options['nodeType'])
            prop = PointerProperty(name=param_label, 
                        description=param_help,
                        type=reference_type)            

        else:
            prop = StringProperty(name=param_label,
                                  default=param_default,
                                  description=param_help, update=update_function)
        renderman_type = param_type

    elif param_type == 'vector' or param_type == 'normal':
        if param_default is None:
            param_default = '0 0 0'
        prop = FloatVectorProperty(name=param_label,
                                   default=param_default, size=3,
                                   subtype="NONE",
                                   description=param_help, update=update_function)
    elif param_type == 'point':
        if param_default is None:
            param_default = '0 0 0'
        prop = FloatVectorProperty(name=param_label,
                                   default=param_default, size=3,
                                   subtype="XYZ",
                                   description=param_help, update=update_function)
        renderman_type = param_type
    elif param_type == 'int2':
        param_type = 'int'
        is_array = 2
        prop = IntVectorProperty(name=param_label,
                                 default=param_default, size=2,
                                 description=param_help, update=update_function)
        renderman_type = 'int'
        prop_meta['arraySize'] = 2   

    elif param_type == 'float2':
        param_type = 'float'
        is_array = 2
        prop = FloatVectorProperty(name=param_label,
                                 default=param_default, size=2,
                                 description=param_help, update=update_function)
        renderman_type = 'float'
        prop_meta['arraySize'] = 2        

    prop_meta['renderman_type'] = renderman_type
    prop_meta['renderman_name'] = renderman_name
    prop_meta['label'] = param_label
    prop_meta['type'] = param_type

    return (param_name, prop_meta, prop)

def set_material_rixparams(node, rman_sg_node, params, mat_name=None):
    # If node is OSL node get properties from dynamic location.
    if node.bl_idname == "PxrOSLPatternNode":

        if getattr(node, "codetypeswitch") == "EXT":
            prefs = bpy.context.preferences.addons[__package__].preferences
            osl_path = user_path(getattr(node, 'shadercode'))
            FileName = os.path.basename(osl_path)
            FileNameNoEXT,ext = os.path.splitext(FileName)
            out_file = os.path.join(
                user_path(prefs.env_vars.out), "shaders", FileName)
            if ext == ".oso":
                if not os.path.exists(out_file) or not os.path.samefile(osl_path, out_file):
                    if not os.path.exists(os.path.join(user_path(prefs.env_vars.out), "shaders")):
                        os.mkdir(os.path.join(user_path(prefs.env_vars.out), "shaders"))
                    shutil.copy(osl_path, out_file)
        for input_name, input in node.inputs.items():
            prop_type = input.renderman_type
            if input.is_linked:
                to_socket = input
                from_socket = input.links[0].from_socket

                param_type = prop_type
                param_name = input_name

                val = get_output_param_str(from_socket.node, mat_name, from_socket, to_socket)

                set_rix_param(params, param_type, param_name, val, is_reference=True)    

            elif type(input) != RendermanNodeSocketStruct:

                param_type = prop_type
                param_name = input_name
                val = string_utils.convert_val(input.default_value, type_hint=prop_type)
                set_rix_param(params, param_type, param_name, val, is_reference=False)                


    # Special case for SeExpr Nodes. Assume that the code will be in a file so
    # that needs to be extracted.
    elif node.bl_idname == "PxrSeExprPatternNode":
        fileInputType = node.codetypeswitch

        for prop_name, meta in node.prop_meta.items():
            if prop_name in ["codetypeswitch", 'filename']:
                pass
            elif prop_name == "internalSearch" and fileInputType == 'INT':
                if node.internalSearch != "":
                    script = bpy.data.texts[node.internalSearch]

                    params.SetString("expression", script.as_string() )
            elif prop_name == "shadercode" and fileInputType == "NODE":
                params.SetString("expression", node.expression)
            else:
                prop = getattr(node, prop_name)
                # if input socket is linked reference that
                if prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:

                    to_socket = node.inputs[prop_name]
                    from_socket = to_socket.links[0].from_socket
                    from_node = to_socket.links[0].from_node

                    param_type = meta['renderman_type']
                    param_name = meta['renderman_name']

                    val = get_output_param_str(
                            from_socket.node, mat_name, from_socket, to_socket)

                    set_rix_param(params, param_type, param_name, val, is_reference=True)                            
                # else output rib
                else:
                    param_type = meta['renderman_type']
                    param_name = meta['renderman_name']

                    val = string_utils.convert_val(prop, type_hint=meta['renderman_type'])
                    set_rix_param(params, param_type, param_name, val, is_reference=False)                          

    else:

        for prop_name, meta in node.prop_meta.items():
            #if prop_name in texture_utils.txmake_options().index:
            #    pass
            #elif node.plugin_name == 'PxrRamp' and prop_name in ['colors', 'positions']:
            #    pass
            if node.plugin_name == 'PxrRamp' and prop_name in ['colors', 'positions']:
                pass

            elif(prop_name in ['sblur', 'tblur', 'notes']):
                pass

            else:
                prop = getattr(node, prop_name)
                # if property group recurse
                if meta['renderman_type'] == 'page':
                    continue
                elif prop_name == 'inputMaterial' or \
                        ('type' in meta and meta['type'] == 'vstruct'):
                    continue

                # if input socket is linked reference that
                elif hasattr(node, 'inputs') and prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:

                    to_socket = node.inputs[prop_name]
                    from_socket = to_socket.links[0].from_socket
                    from_node = to_socket.links[0].from_node

                    param_type = meta['renderman_type']
                    param_name = meta['renderman_name']

                    if 'arraySize' in meta:
                        pass
                    else:
                        val = get_output_param_str(
                                from_node, mat_name, from_socket, to_socket)

                        set_rix_param(params, param_type, param_name, val, is_reference=True)                  

                # see if vstruct linked
                elif is_vstruct_and_linked(node, prop_name):
                    vstruct_name, vstruct_member = meta[
                        'vstructmember'].split('.')
                    from_socket = node.inputs[
                        vstruct_name].links[0].from_socket

                    temp_mat_name = mat_name

                    if from_socket.node.bl_idname == 'ShaderNodeGroup':
                        ng = from_socket.node.node_tree
                        group_output = next((n for n in ng.nodes if n.bl_idname == 'NodeGroupOutput'),
                                            None)
                        if group_output is None:
                            return False

                        in_sock = group_output.inputs[from_socket.name]
                        if len(in_sock.links):
                            from_socket = in_sock.links[0].from_socket
                            temp_mat_name = mat_name + '.' + from_socket.node.name

                    vstruct_from_param = "%s_%s" % (
                        from_socket.identifier, vstruct_member)
                    if vstruct_from_param in from_socket.node.output_meta:
                        actual_socket = from_socket.node.output_meta[
                            vstruct_from_param]

                        param_type = meta['renderman_type']
                        param_name = meta['renderman_name']

                        node_meta = getattr(
                            node, 'shader_meta') if node.bl_idname == "PxrOSLPatternNode" else node.output_meta                        
                        node_meta = node_meta.get(vstruct_from_param)
                        is_reference = True
                        val = get_output_param_str(
                               from_socket.node, temp_mat_name, actual_socket)
                        if node_meta:
                            expr = node_meta.get('vstructConditionalExpr')
                            # check if we should connect or just set a value
                            if expr:
                                if expr.split(' ')[0] == 'set':
                                    val = 1
                                    is_reference = False                        
                        set_rix_param(params, param_type, param_name, val, is_reference=is_reference)

                    else:
                        rfb_log().warning('Warning! %s not found on %s' %
                              (vstruct_from_param, from_socket.node.name))

                # else output rib
                else:
                    # if struct is not linked continue
                    if meta['renderman_type'] in ['struct', 'enum']:
                        continue

                    param_type = meta['renderman_type']
                    param_name = meta['renderman_name']
                    val = None
                    isArray = False
                    arrayLen = 0

                    # if this is a gain on PxrSurface and the lobe isn't
                    # enabled
                    
                    if node.bl_idname == 'PxrSurfaceBxdfNode' and \
                            prop_name in __GAINS_TO_ENABLE__ and \
                            not getattr(node, __GAINS_TO_ENABLE__[prop_name]):
                        val = [0, 0, 0] if meta[
                            'renderman_type'] == 'color' else 0
                        

                    elif 'options' in meta and meta['options'] == 'texture' \
                            and node.bl_idname != "PxrPtexturePatternNode" or \
                            ('widget' in meta and meta['widget'] == 'assetIdInput' and prop_name != 'iesProfile'):

                        tx_node_id = texture_utils.generate_node_id(node, param_name)
                        val = string_utils.convert_val(texture_utils.get_txmanager().get_txfile_from_id(tx_node_id), type_hint=meta['renderman_type'])
                        
                        # FIXME: Need a better way to check for a frame variable
                        if '{F' in prop:
                            rman_sg_node.is_frame_sensitive = True
                        else:
                            rman_sg_node.is_frame_sensitive = False                            
                    elif 'arraySize' in meta:
                        isArray = True
                        if type(prop) == int:
                            prop = [prop]
                        val = string_utils.convert_val(prop)
                        arrayLen = len(prop)
                    else:

                        val = string_utils.convert_val(prop, type_hint=meta['renderman_type'])

                    if isArray:
                        pass
                    else:
                        set_rix_param(params, param_type, param_name, val, is_reference=False)
                        

    if node.plugin_name == 'PxrRamp':
        nt = bpy.data.node_groups[node.node_group]
        if nt:
            dummy_ramp = nt.nodes['ColorRamp']
            colors = []
            positions = []
            # double the start and end points
            positions.append(float(dummy_ramp.color_ramp.elements[0].position))
            colors.extend(dummy_ramp.color_ramp.elements[0].color[:3])
            for e in dummy_ramp.color_ramp.elements:
                positions.append(float(e.position))
                colors.extend(e.color[:3])
            positions.append(
                float(dummy_ramp.color_ramp.elements[-1].position))
            colors.extend(dummy_ramp.color_ramp.elements[-1].color[:3])

            params.SetFloatArray("colorRamp_Knots", positions, len(positions))
            params.SetColorArray("colorRamp_Colors", colors, len(positions))

            rman_interp_map = { 'LINEAR': 'linear', 'CONSTANT': 'constant'}
            interp = rman_interp_map.get(dummy_ramp.color_ramp.interpolation,'catmull-rom')
            params.SetString("colorRamp_Interpolation", interp )
    return params      

def set_rixparams(node, rman_sg_node, params, light):
    for prop_name, meta in node.prop_meta.items():
        if not hasattr(node, prop_name):
            continue
        prop = getattr(node, prop_name)
        # if property group recurse
        if meta['renderman_type'] == 'page' or prop_name == 'notes' or meta['renderman_type'] == 'enum':
            continue
        else:
            type = meta['renderman_type']
            name = meta['renderman_name']
            # if struct is not linked continue
            if 'arraySize' in meta:
                set_rix_param(params, type, name, string_utils.convert_val(prop), is_reference=False, is_array=True, array_len=len(prop))

            elif ('widget' in meta and meta['widget'] == 'assetIdInput' and prop_name != 'iesProfile'):
                if light:
                    tx_node_id = texture_utils.generate_node_id(light, prop_name)
                else:
                    tx_node_id = texture_utils.generate_node_id(node, prop_name)

                params.SetString(name, texture_utils.get_txmanager().get_txfile_from_id(tx_node_id))
                
                # FIXME: Need a better way to check for a frame variable
                if '{F' in prop:
                    rman_sg_node.is_frame_sensitive = True
                else:
                    rman_sg_node.is_frame_sensitive = False

            else:
                val = string_utils.convert_val(prop, type_hint=type)
                set_rix_param(params, type, name, val)

        if node.plugin_name in ['PxrBlockerLightFilter', 'PxrRampLightFilter', 'PxrRodLightFilter']:
            rm = light.renderman
            nt = light.node_tree
            if nt and rm.float_ramp_node in nt.nodes.keys():
                knot_param = 'ramp_Knots' if node.plugin_name == 'PxrRampLightFilter' else 'falloff_Knots'
                float_param = 'ramp_Floats' if node.plugin_name == 'PxrRampLightFilter' else 'falloff_Floats'
                params.Remove('%s' % knot_param)
                params.Remove('%s' % float_param)
                float_node = nt.nodes[rm.float_ramp_node]
                curve = float_node.mapping.curves[0]
                knots = []
                vals = []
                # double the start and end points
                knots.append(curve.points[0].location[0])
                vals.append(curve.points[0].location[1])
                for p in curve.points:
                    knots.append(p.location[0])
                    vals.append(p.location[1])
                knots.append(curve.points[-1].location[0])
                vals.append(curve.points[-1].location[1])

                params.SetFloatArray(knot_param, knots, len(knots))
                params.SetFloatArray(float_param, vals, len(vals))

            if nt and rm.color_ramp_node in nt.nodes.keys():
                params.Remove('colorRamp_Knots')
                color_node = nt.nodes[rm.color_ramp_node]
                color_ramp = color_node.color_ramp
                colors = []
                positions = []
                # double the start and end points
                positions.append(float(color_ramp.elements[0].position))
                colors.extend(color_ramp.elements[0].color[:3])
                for e in color_ramp.elements:
                    positions.append(float(e.position))
                    colors.extend(e.color[:3])
                positions.append(
                    float(color_ramp.elements[-1].position))
                colors.extend(color_ramp.elements[-1].color[:3])

                params.SetFloatArray('colorRamp_Knots', positions, len(positions))
                params.SetColorArray('colorRamp_Colors', colors, len(positions))               


def property_group_to_rixparams(node, rman_sg_node, sg_node, light=None, mat_name=None):

    params = sg_node.params
    if mat_name:
        set_material_rixparams(node, rman_sg_node, params, mat_name=mat_name)
    else:
        set_rixparams(node, rman_sg_node, params, light=light)


def portal_inherit_dome_params(portal_node, dome, dome_node, rixparams):

    tx_node_id = texture_utils.generate_node_id(dome, 'lightColorMap')
    rixparams.SetString('domeColorMap', string_utils.convert_val(texture_utils.get_txmanager().get_txfile_from_id(tx_node_id)))

    prop = getattr(portal_node, 'colorMapGamma')
    if string_utils.convert_val(prop) == (1.0, 1.0, 1.0):
        prop = getattr(dome_node, 'colorMapGamma')
        rixparams.SetVector('colorMapGamma', string_utils.convert_val(prop, type_hint='vector'))

    prop = getattr(portal_node, 'colorMapSaturation')
    if string_utils.convert_val(prop) == 1.0:
        prop = getattr(dome_node, 'colorMapSaturation')
        rixparams.SetFloat('colorMapSaturation', string_utils.convert_val(prop, type_hint='float'))

    prop = getattr(portal_node, 'enableTemperature')
    if string_utils.convert_val(prop):
        prop = getattr(dome_node, 'enableTemperature')
        rixparams.SetInteger('enableTemperature', string_utils.convert_val(prop, type_hint='int'))        
        prop = getattr(dome_node, 'temperature')
        rixparams.SetFloat('temperature', string_utils.convert_val(prop, type_hint='float'))   

    prop = getattr(dome_node, 'intensity')
    rixparams.SetFloat('intensity', string_utils.convert_val(prop, type_hint='float'))        
    prop = getattr(dome_node, 'exposure')
    rixparams.SetFloat('exposure', string_utils.convert_val(prop, type_hint='float')) 
    prop = getattr(dome_node, 'specular')
    rixparams.SetFloat('specular', string_utils.convert_val(prop, type_hint='float'))  
    prop = getattr(dome_node, 'diffuse')
    rixparams.SetFloat('diffuse', string_utils.convert_val(prop, type_hint='float'))   
    prop = getattr(dome_node, 'lightColor')
    rixparams.SetColor('lightColor', string_utils.convert_val(prop, type_hint='color')) 