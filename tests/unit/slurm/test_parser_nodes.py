"""Tests for parsing scontrol nodes output."""

from stoei.slurm.parser import parse_scontrol_nodes_output


class TestParseScontrolNodesOutput:
    """Tests for parse_scontrol_nodes_output."""

    def test_parse_single_node(self) -> None:
        """Test parsing output for a single node."""
        output = """NodeName=node01
   State=IDLE
   CPUTot=16
   CPUAlloc=0
   RealMemory=64000
   AllocMem=0
   Partitions=gpu,cpu"""
        nodes = parse_scontrol_nodes_output(output)
        assert len(nodes) == 1
        assert nodes[0]["NodeName"] == "node01"
        assert nodes[0]["State"] == "IDLE"
        assert nodes[0]["CPUTot"] == "16"

    def test_parse_multiple_nodes(self) -> None:
        """Test parsing output for multiple nodes."""
        output = """NodeName=node01
   State=IDLE
   CPUTot=16

NodeName=node02
   State=ALLOCATED
   CPUTot=16 CPUAlloc=8"""
        nodes = parse_scontrol_nodes_output(output)
        assert len(nodes) == 2
        assert nodes[0]["NodeName"] == "node01"
        assert nodes[1]["NodeName"] == "node02"

    def test_parse_node_with_continuation_lines(self) -> None:
        """Test parsing node with continuation lines."""
        output = """NodeName=node01
   State=MIXED
   CPUTot=16 CPUAlloc=8
   RealMemory=64000 AllocMem=32000
   Gres=gpu:a100:4"""
        nodes = parse_scontrol_nodes_output(output)
        assert len(nodes) == 1
        assert nodes[0]["NodeName"] == "node01"
        assert nodes[0]["State"] == "MIXED"

    def test_parse_empty_output(self) -> None:
        """Test parsing empty output."""
        nodes = parse_scontrol_nodes_output("")
        assert nodes == []

    def test_parse_whitespace_only(self) -> None:
        """Test parsing whitespace-only output."""
        nodes = parse_scontrol_nodes_output("   \n\n   ")
        assert nodes == []

    def test_parse_node_with_gres(self) -> None:
        """Test parsing node with GPU resources."""
        output = """NodeName=gpu-node-01
   State=ALLOCATED
   CPUTot=32 CPUAlloc=16
   RealMemory=128000 AllocMem=64000
   Gres=gpu:a100:4"""
        nodes = parse_scontrol_nodes_output(output)
        assert len(nodes) == 1
        assert nodes[0]["Gres"] == "gpu:a100:4"

    def test_parse_node_with_partitions(self) -> None:
        """Test parsing node with multiple partitions."""
        output = """NodeName=node01
   State=IDLE
   Partitions=gpu,cpu,highmem"""
        nodes = parse_scontrol_nodes_output(output)
        assert len(nodes) == 1
        assert nodes[0]["Partitions"] == "gpu,cpu,highmem"

    def test_parse_node_with_reason(self) -> None:
        """Test parsing node with reason field."""
        output = """NodeName=node01
   State=DOWN
   Reason=Not responding"""
        nodes = parse_scontrol_nodes_output(output)
        assert len(nodes) == 1
        assert nodes[0]["State"] == "DOWN"
        assert nodes[0]["Reason"] == "Not responding"
