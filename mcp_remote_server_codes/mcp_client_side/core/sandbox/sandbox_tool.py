"""
Sandbox MCP Tool
================
Exposes sandbox execution as an MCP tool for the agent.

This allows the agent to:
- Execute Python code safely
- Run JavaScript/Node.js code
- Execute shell commands
- Test synthesized skills (Day 6)
- Validate generated tools (Day 9)
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass

from .code_runner import get_code_runner, CodeRunner
from .docker_executor import ExecutionResult, ExecutionStatus
from .resource_limits import ExecutionTier


@dataclass
class SandboxToolResult:
    """Result formatted for MCP tool response."""
    success: bool
    output: str
    error: Optional[str] = None
    execution_time: float = 0.0
    language: str = "python"


class SandboxTool:
    """
    MCP Tool wrapper for sandbox execution.

    Provides a clean interface for agent to execute code.
    """

    def __init__(self):
        self._runner: Optional[CodeRunner] = None

    async def initialize(self) -> bool:
        """Initialize the sandbox tool."""
        self._runner = await get_code_runner()
        return True

    async def execute_python(
        self,
        code: str,
        tier: str = "standard",
    ) -> SandboxToolResult:
        """
        Execute Python code safely in sandbox.

        Args:
            code: Python code to execute
            tier: Resource tier (minimal, standard, intensive)

        Returns:
            SandboxToolResult with output
        """
        if not self._runner:
            await self.initialize()

        exec_tier = ExecutionTier(tier) if tier in [t.value for t in ExecutionTier] else ExecutionTier.STANDARD

        result = await self._runner.run(code, language="python", tier=exec_tier)

        return SandboxToolResult(
            success=result.status == ExecutionStatus.SUCCESS,
            output=result.output,
            error=result.error,
            execution_time=result.execution_time,
            language="python",
        )

    async def execute_javascript(
        self,
        code: str,
        tier: str = "standard",
    ) -> SandboxToolResult:
        """
        Execute JavaScript code safely in sandbox.

        Args:
            code: JavaScript code to execute
            tier: Resource tier

        Returns:
            SandboxToolResult with output
        """
        if not self._runner:
            await self.initialize()

        exec_tier = ExecutionTier(tier) if tier in [t.value for t in ExecutionTier] else ExecutionTier.STANDARD

        result = await self._runner.run(code, language="javascript", tier=exec_tier)

        return SandboxToolResult(
            success=result.status == ExecutionStatus.SUCCESS,
            output=result.output,
            error=result.error,
            execution_time=result.execution_time,
            language="javascript",
        )

    async def execute_shell(
        self,
        command: str,
        tier: str = "minimal",
    ) -> SandboxToolResult:
        """
        Execute shell command safely in sandbox.

        Args:
            command: Shell command to execute
            tier: Resource tier (defaults to minimal for shell)

        Returns:
            SandboxToolResult with output
        """
        if not self._runner:
            await self.initialize()

        exec_tier = ExecutionTier(tier) if tier in [t.value for t in ExecutionTier] else ExecutionTier.MINIMAL

        result = await self._runner.run(command, language="bash", tier=exec_tier)

        return SandboxToolResult(
            success=result.status == ExecutionStatus.SUCCESS,
            output=result.output,
            error=result.error,
            execution_time=result.execution_time,
            language="bash",
        )

    async def test_skill(
        self,
        skill_code: str,
        test_inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Test a synthesized skill in sandbox.

        Used by Day 6 Skill Synthesis to validate new skills.

        Args:
            skill_code: The skill implementation code
            test_inputs: Test input data

        Returns:
            Test result with success status
        """
        if not self._runner:
            await self.initialize()

        # Wrap skill code with test harness
        test_code = f'''
import json

# Skill implementation
{skill_code}

# Test inputs
test_inputs = {repr(test_inputs)}

# Run skill (assuming skill defines a 'run' function)
try:
    result = run(**test_inputs)
    print(json.dumps({{"success": True, "result": result}}))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
'''

        result = await self._runner.run(
            test_code,
            language="python",
            tier=ExecutionTier.STANDARD,
        )

        if result.status == ExecutionStatus.SUCCESS:
            try:
                import json
                output = json.loads(result.output.strip())
                return output
            except:
                return {"success": True, "result": result.output}
        else:
            return {
                "success": False,
                "error": result.error or "Execution failed",
            }

    async def validate_tool_code(
        self,
        tool_code: str,
    ) -> Dict[str, Any]:
        """
        Validate dynamically generated tool code.

        Used by Day 9 Dynamic Tool Creation.

        Args:
            tool_code: Generated tool code

        Returns:
            Validation result
        """
        if not self._runner:
            await self.initialize()

        # Try to compile/parse the code without executing
        validation_code = f'''
import ast
import json

code = """{tool_code}"""

try:
    # Parse the code
    tree = ast.parse(code)

    # Check for function definitions
    functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

    print(json.dumps({{
        "valid": True,
        "functions": functions,
        "message": "Code is syntactically valid"
    }}))
except SyntaxError as e:
    print(json.dumps({{
        "valid": False,
        "error": str(e),
        "line": e.lineno,
        "message": f"Syntax error at line {{e.lineno}}: {{e.msg}}"
    }}))
except Exception as e:
    print(json.dumps({{
        "valid": False,
        "error": str(e),
        "message": f"Validation error: {{str(e)}}"
    }}))
'''

        result = await self._runner.run(
            validation_code,
            language="python",
            tier=ExecutionTier.MINIMAL,
        )

        if result.status == ExecutionStatus.SUCCESS:
            try:
                import json
                return json.loads(result.output.strip())
            except:
                return {"valid": False, "error": "Failed to parse validation result"}
        else:
            return {
                "valid": False,
                "error": result.error or "Validation execution failed",
            }


# Singleton
_sandbox_tool: Optional[SandboxTool] = None


async def get_sandbox_tool() -> SandboxTool:
    """Get or create sandbox tool instance."""
    global _sandbox_tool

    if _sandbox_tool is None:
        _sandbox_tool = SandboxTool()
        await _sandbox_tool.initialize()

    return _sandbox_tool


# ═══════════════════════════════════════════════════════════════════════════
# MCP TOOL DEFINITIONS (for integration with your MCP server)
# ═══════════════════════════════════════════════════════════════════════════

def register_sandbox_tools(mcp_server):
    """
    Register sandbox tools with your MCP server.

    Call this during startup:
        from core.sandbox.sandbox_tool import register_sandbox_tools
        register_sandbox_tools(mcp)
    """

    @mcp_server.tool()
    async def execute_python(code: str, tier: str = "standard") -> str:
        """
        Safely execute Python code in an isolated sandbox.

        The code runs in a Docker container with:
        - Limited CPU and memory
        - No network access
        - Read-only filesystem
        - 30 second timeout

        Args:
            code: Python code to execute
            tier: Resource tier (minimal, standard, intensive)

        Returns:
            Execution output or error message
        """
        tool = await get_sandbox_tool()
        result = await tool.execute_python(code, tier)

        if result.success:
            return f"✅ Output:\n{result.output}"
        else:
            return f"❌ Error: {result.error}\nOutput: {result.output}"

    @mcp_server.tool()
    async def execute_javascript(code: str) -> str:
        """
        Safely execute JavaScript code in an isolated sandbox.

        Args:
            code: JavaScript code to execute

        Returns:
            Execution output or error message
        """
        tool = await get_sandbox_tool()
        result = await tool.execute_javascript(code)

        if result.success:
            return f"✅ Output:\n{result.output}"
        else:
            return f"❌ Error: {result.error}"

    print("[SandboxTool] Registered execute_python and execute_javascript tools")
