# -*- coding: utf-8 -*-
import ast, os, sys, tkinter as tk
from tkinter import filedialog

# ------------------ 工具函数 ------------------
def snake_to_camel(name: str) -> str:
    return ''.join(p.capitalize() for p in name.split('_'))

def upper_first_letter(name: str) -> str:
    return name[0].upper() + name[1:] if name else name

def pytype_to_uetype(annotation):
    if annotation is None:
        return "const FString&"
    if isinstance(annotation, ast.Name):
        t = annotation.id
        return {
            "str": "const FString&",
            "int": "int32",
            "float": "float",
            "bool": "bool"
        }.get(t, "FString")
    return "const FString&"

def is_ufunction_override(decorator):
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Attribute) and func.attr == 'ufunction':
            if isinstance(func.value, ast.Name) and func.value.id == 'unreal':
                for kw in decorator.keywords:
                    if kw.arg == 'override' and isinstance(kw.value, ast.Constant) and kw.value.value:
                        return True
    return False

def is_staticmethod(decorator):
    if isinstance(decorator, ast.Name) and decorator.id == "staticmethod":
        return True
    if isinstance(decorator, ast.Attribute) and decorator.attr == "staticmethod":
        return True
    return False

def has_unreal_uclass(decorator_list):
    for d in decorator_list:
        if isinstance(d, ast.Call):
            func = d.func
            if isinstance(func, ast.Attribute) and func.attr == 'uclass':
                if isinstance(func.value, ast.Name) and func.value.id == 'unreal':
                    return True
    return False

def make_py_param_fmt(params):
    """生成 FString::Printf 的格式字符串和参数列表"""
    if not params:
        return "", ""
    fmt_list = []
    val_list = []
    for ptype, pname in params:
        fmt_list.append("%s")
        val_list.append(f"*{pname}")
    fmt = ", ".join(fmt_list)
    values = ", ".join(val_list)
    return fmt, values

# ------------------ 模板 ------------------
HEADER_TEMPLATE = """#pragma once
#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "{ModuleName}.generated.h"

{ClassDecls}
"""

UCLASS_TEMPLATE = """
UCLASS()
class {ModuleNameUpper}_API {ClassName} : public UObject
{{
    GENERATED_BODY()
public:
    static {ClassName}* Get();

    // ---- 静态方法 ----
{StaticDecls}

    // ---- 非静态方法 ----
{InstanceDecls}
}};
"""

FCLASS_TEMPLATE = """
USTRUCT(BlueprintType)
struct {ModuleNameUpper}_API {ClassName}
{{
    GENERATED_BODY()

    // ---- 静态方法 ----
{StaticDecls}

    // ---- 非静态方法 ----
{InstanceDecls}
}};
"""

CPP_TEMPLATE = """#include "{ModuleName}.h"
#include "IPythonScriptPlugin.h"

{ClassDefs}
"""

UCLASS_GET_IMPL = """{ClassName}* {ClassName}::Get()
{{
    static TWeakObjectPtr<{ClassName}> Cached;
    if (Cached.IsValid()) return Cached.Get();

    TArray<UClass*> PythonClasses;
    GetDerivedClasses({ClassName}::StaticClass(), PythonClasses);

    if (PythonClasses.Num() == 0) {{
        FPythonCommandEx Cmd;
        Cmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;
        Cmd.Command = TEXT("import {ModuleName}");
        IPythonScriptPlugin::Get()->ExecPythonCommandEx(Cmd);
        GetDerivedClasses({ClassName}::StaticClass(), PythonClasses);
    }}

    if (PythonClasses.Num() > 0) {{
        Cached = Cast<{ClassName}>(PythonClasses.Last()->GetDefaultObject());
        return Cached.Get();
    }}
    return nullptr;
}}
"""

# ------------------ 生成器 ------------------
def gen_bindings(pyfile, outdir, module_name=None):
    if not os.path.exists(pyfile):
        raise FileNotFoundError(f"找不到 Python 文件: {pyfile}")

    if not module_name:
        module_name = os.path.splitext(os.path.basename(pyfile))[0]
    module_upper = module_name.upper()

    with open(pyfile, 'r', encoding='utf-8-sig') as f:
        tree = ast.parse(f.read())

    # key = class name, value = dict
    classes = {}

    # ---- 先放模块级函数 ----
    top_class_name = f"U{upper_first_letter(module_name)}"
    classes[top_class_name] = {
        "is_uclass": True,
        "static_funcs": [],
        "instance_funcs": []
    }

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            params = [(pytype_to_uetype(arg.annotation), upper_first_letter(arg.arg)) for arg in node.args.args]
            classes[top_class_name]["static_funcs"].append({
                "name": node.name,
                "camel": snake_to_camel(node.name),
                "params": params
            })
        elif isinstance(node, ast.ClassDef):
            cname = node.name
            is_u = has_unreal_uclass(node.decorator_list)
            prefix = "U" if is_u else "F"
            cpp_name = f"{prefix}{upper_first_letter(cname)}"
            if cpp_name not in classes:
                classes[cpp_name] = {
                    "is_uclass": is_u,
                    "static_funcs": [],
                    "instance_funcs": []
                }
            for f in node.body:
                if not isinstance(f, ast.FunctionDef):
                    continue
                is_override = any(is_ufunction_override(d) for d in f.decorator_list)
                has_self = len(f.args.args) > 0 and f.args.args[0].arg == "self"
                is_static = is_staticmethod(f.decorator_list[0]) if f.decorator_list else False
                if not has_self:
                    is_static = True
                arg_list = f.args.args if is_static else f.args.args[1:]
                params = [(pytype_to_uetype(arg.annotation), upper_first_letter(arg.arg)) for arg in arg_list]
                info = {
                    "name": f.name,
                    "camel": snake_to_camel(f.name),
                    "params": params,
                    "is_override": is_override,
                    "is_static": is_static
                }
                if is_static:
                    classes[cpp_name]["static_funcs"].append(info)
                else:
                    classes[cpp_name]["instance_funcs"].append(info)

    # ---- 头文件 ----
    class_decls = []
    for cname, info in classes.items():
        static_decls = "\n".join([
            f"    UFUNCTION(BlueprintCallable, Category=\"{module_name}\")\n"
            f"    static FString {f['camel']}({', '.join([ptype+' '+pname for ptype,pname in f['params']])});"
            for f in info["static_funcs"]
        ]) or "    // (无静态方法)"

        instance_decls_list = []
        for f in info["instance_funcs"]:
            param_str = ", ".join([f"{ptype} {pname}" for ptype,pname in f['params']])
            ret_type = "bool" if f['is_override'] else "FString"
            if f['is_override']:
                instance_decls_list.append(
                    f"    UFUNCTION(BlueprintImplementableEvent, Category=\"{module_name}\")\n"
                    f"    {ret_type} {f['camel']}({param_str});"
                )
                instance_decls_list.append(
                    f"    UFUNCTION(BlueprintCallable, Category=\"{module_name}\")\n"
                    f"    static {ret_type} Call{f['camel']}({param_str});"
                )
            else:
                instance_decls_list.append(
                    f"    UFUNCTION(BlueprintCallable, Category=\"{module_name}\")\n"
                    f"    {ret_type} {f['camel']}({param_str});"
                )
        instance_decls = "\n".join(instance_decls_list) if instance_decls_list else "    // (无实例方法)"

        if info["is_uclass"]:
            decl = UCLASS_TEMPLATE.format(
                ClassName=cname,
                ModuleNameUpper=module_upper,
                StaticDecls=static_decls,
                InstanceDecls=instance_decls
            )
        else:
            decl = FCLASS_TEMPLATE.format(
                ClassName=cname,
                ModuleNameUpper=module_upper,
                StaticDecls=static_decls,
                InstanceDecls=instance_decls
            )
        class_decls.append(decl)

    header_code = HEADER_TEMPLATE.format(
        ModuleName=module_name,
        ClassDecls="\n".join(class_decls)
    )

    # ---- 源文件 ----
    class_defs = []
    for cname, info in classes.items():
        static_defs_list = []
        for f in info["static_funcs"]:
            fmt, values = make_py_param_fmt(f['params'])
            param_str = ", ".join([ptype+' '+pname for ptype,pname in f['params']])
            static_defs_list.append(
                f"FString {cname}::{f['camel']}({param_str})\n{{\n"
                f"    FPythonCommandEx Cmd;\n"
                f"    FString PyCmd = FString::Printf(TEXT(\"import {module_name}; {module_name}.{f['name']}({fmt})\"), {values});\n"
                f"    Cmd.Command = PyCmd;\n"
                f"    Cmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;\n"
                f"    IPythonScriptPlugin::Get()->ExecPythonCommandEx(Cmd);\n"
                f"    return FString();\n}}\n"
            )
        static_defs = "\n".join(static_defs_list) if static_defs_list else "// (无静态方法)"

        instance_defs_list = []
        for f in info["instance_funcs"]:
            param_str = ", ".join([f"{ptype} {pname}" for ptype,pname in f['params']])
            arg_names = ", ".join([pname for _, pname in f['params']])
            ret_type = "bool" if f['is_override'] else "FString"
            if f['is_override']:
                instance_defs_list.append(
                    f"{ret_type} {cname}::Call{f['camel']}({param_str})\n{{\n"
                    f"    {cname}* Bridge = {cname}::Get();\n"
                    f"    if (!Bridge) return {ret_type}();\n"
                    f"    return Bridge->{f['camel']}({arg_names});\n}}\n"
                )
            else:
                fmt, values = make_py_param_fmt(f['params'])
                instance_defs_list.append(
                    f"{ret_type} {cname}::{f['camel']}({param_str})\n{{\n"
                    f"    FPythonCommandEx Cmd;\n"
                    f"    FString PyCmd = FString::Printf(TEXT(\"import {module_name}; {module_name}.{f['name']}({fmt})\"), {values});\n"
                    f"    Cmd.Command = PyCmd;\n"
                    f"    Cmd.ExecutionMode = EPythonCommandExecutionMode::ExecuteStatement;\n"
                    f"    IPythonScriptPlugin::Get()->ExecPythonCommandEx(Cmd);\n"
                    f"    return {ret_type}();\n}}\n"
                )
        instance_defs = "\n".join(instance_defs_list) if instance_defs_list else "// (无实例方法)"

        defs = ""
        if info["is_uclass"]:
            defs += UCLASS_GET_IMPL.format(ClassName=cname, ModuleName=module_name)
        defs += static_defs + "\n" + instance_defs
        class_defs.append(defs)

    cpp_code = CPP_TEMPLATE.format(
        ModuleName=module_name,
        ClassDefs="\n".join(class_defs)
    )

    # ---- 输出 ----
    os.makedirs(outdir, exist_ok=True)
    hfile = os.path.join(outdir, f"{module_name}.h")
    cppfile = os.path.join(outdir, f"{module_name}.cpp")
    with open(hfile, 'w', encoding='utf-8') as f:
        f.write(header_code)
    with open(cppfile, 'w', encoding='utf-8') as f:
        f.write(cpp_code)
    print(f"✅ 生成完成: {hfile}, {cppfile}")

# ------------------ 主程序 ------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python gen_bindings.py <module.py>")
        sys.exit(1)
    pyfile = sys.argv[1]
    if not os.path.exists(pyfile):
        print(f"Python 文件不存在: {pyfile}")
        sys.exit(1)
    root = tk.Tk()
    root.withdraw()
    outdir = filedialog.askdirectory(title="选择文件输出目录")
    if not outdir:
        print("未选择输出目录，程序退出。")
        sys.exit(1)
    gen_bindings(pyfile, outdir)