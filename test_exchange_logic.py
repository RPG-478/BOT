import ast
from pathlib import Path

source = Path(__file__).with_name("cogs").joinpath("ddd_system.py").read_text()
tree = ast.parse(source)
names = {"COINS_PER_EXP", "exchange_values"}
nodes = []
for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(target, "id", None) in names for target in node.targets):
        nodes.append(node)
    elif isinstance(node, ast.FunctionDef) and node.name == "exchange_values":
        nodes.append(node)
namespace = {"add_experience": lambda level, exp, amount: (level + (exp + amount) // 100, (exp + amount) % 100)}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "ddd_system.py", "exec"), namespace)
exchange_values = namespace["exchange_values"]
assert exchange_values(2, "exp_to_coin", 5, 25, 100) == (5, 23, 200)
assert exchange_values(2, "coin_to_exp", 5, 25, 100) == (5, 27, 0)
assert exchange_values(80, "coin_to_exp", 5, 25, 5000) == (6, 5, 1000)
for call in (
    lambda: exchange_values(0, "coin_to_exp", 5, 0, 1000),
    lambda: exchange_values(1, "bad", 5, 0, 1000),
    lambda: exchange_values(1, "coin_to_exp", 5, 0, 49),
    lambda: exchange_values(1, "exp_to_coin", 5, 0, 1000),
):
    try:
        call()
    except ValueError:
        pass
    else:
        raise AssertionError("invalid exchange input was accepted")
print("exchange logic: OK")
