"""
═══════════════════════════════════════════════════════════════════════════════
SKILL STORE - Day 5: Skill Library & Workflow Recording
═══════════════════════════════════════════════════════════════════════════════

Stores user-approved skills (workflows) for future reuse.
Skills are recorded when users click the like button on successful responses.

Key Features:
- Manual skill recording via like button
- LLM-based skill formatting and naming
- Dual embedding search (query + description)
- Thread/conversation tracking for provenance
- Usage analytics and success rate tracking
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import uuid

from motor.motor_asyncio import AsyncIOMotorClient


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class SkillType(Enum):
    """Types of skills that can be recorded."""
    TOOL_WORKFLOW = "tool_workflow"      # Uses MCP tools
    REASONING = "reasoning"               # Pure reasoning/explanation
    HYBRID = "hybrid"                     # Combines tools + reasoning
    MULTI_STEP = "multi_step"            # Multiple sequential actions


@dataclass
class SkillWorkflowStep:
    """A single step in a skill workflow."""
    step_number: int
    action_type: str                      # "tool_call" | "reasoning" | "confirmation"
    tool_name: Optional[str] = None       # Tool used (if tool_call)
    tool_parameters: Dict = field(default_factory=dict)
    description: str = ""                 # What this step does


@dataclass
class Skill:
    """Represents a learned skill."""
    skill_id: str
    name: str                             # LLM-generated readable name
    description: str                      # LLM-generated description
    skill_type: SkillType

    # The workflow
    original_user_query: str              # What user asked
    llm_response: str                     # Full LLM response
    workflow_steps: List[SkillWorkflowStep]
    tools_used: List[str]                 # Quick lookup for tool-based skills

    # Reasoning/Thinking (Day 5.5 - Chain of Thought)
    reasoning_steps: List[str] = field(default_factory=list)  # Step-by-step thinking
    reasoning_raw: str = ""               # Raw thinking text

    # Embeddings for semantic search
    query_embedding: Optional[List[float]] = None      # 384-dim
    description_embedding: Optional[List[float]] = None # 384-dim

    # Provenance
    conversation_id: str = ""             # Thread where skill was learned
    user_id: str = ""                     # Who recorded this skill

    # Analytics
    use_count: int = 0
    success_count: int = 0
    success_rate: float = 1.0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None

    # Status
    is_active: bool = True
    version: int = 1


# ═══════════════════════════════════════════════════════════════════════════════
# SKILL STORE CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class SkillStore:
    """
    MongoDB-backed store for learned skills.

    Collections:
    - learned_skills: Main skill storage with embeddings
    - skill_usage_analytics: Track skill usage patterns
    """

    def __init__(
        self,
        connection_string: str = "mongodb://localhost:27017",
        database_name: str = "agentic_bot"
    ):
        """Initialize connection to MongoDB."""
        self.client = AsyncIOMotorClient(connection_string)
        self.db = self.client[database_name]

        # Collections with clear naming
        self.learned_skills = self.db["learned_skills"]
        self.skill_usage_analytics = self.db["skill_usage_analytics"]

        # Embedding model (lazy load)
        self._embedding_model = None

        print(f"[SkillStore] Initialized with database: {database_name}")

    async def setup(self) -> None:
        """Create indexes for efficient querying."""
        # learned_skills indexes
        await self.learned_skills.create_index("skill_id", unique=True)
        await self.learned_skills.create_index("conversation_id")
        await self.learned_skills.create_index("user_id")
        await self.learned_skills.create_index("skill_type")
        await self.learned_skills.create_index("tools_used")
        await self.learned_skills.create_index("is_active")
        await self.learned_skills.create_index("created_at")
        await self.learned_skills.create_index([("use_count", -1)])  # Most used first

        # skill_usage_analytics indexes
        await self.skill_usage_analytics.create_index("skill_id")
        await self.skill_usage_analytics.create_index("used_at")
        await self.skill_usage_analytics.create_index("conversation_id")

        print("[SkillStore] Indexes created successfully")

    def _get_embedding_model(self):
        """Lazy load embedding model."""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                print("[SkillStore] Loaded embedding model: all-MiniLM-L6-v2")
            except ImportError:
                print("[SkillStore] Warning: sentence-transformers not installed")
                return None
        return self._embedding_model

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate 384-dimensional embedding for text."""
        model = self._get_embedding_model()
        if model is None:
            return None

        try:
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            print(f"[SkillStore] Embedding generation failed: {e}")
            return None

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import numpy as np

        a = np.array(vec1)
        b = np.array(vec2)

        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(dot_product / (norm_a * norm_b))

    # ═══════════════════════════════════════════════════════════════════════════
    # SKILL STORAGE
    # ════════════════════��══════════════════════════════════════════════════════

    async def store_skill(
        self,
        name: str,
        description: str,
        skill_type: str,
        original_user_query: str,
        llm_response: str,
        workflow_steps: List[Dict],
        tools_used: List[str],
        conversation_id: str,
        user_id: str = "default",
        reasoning_steps: List[str] = None,  # Day 5.5: Chain of thought
        reasoning_raw: str = "",            # Day 5.5: Raw thinking text
    ) -> str:
        """
        Store a new learned skill.

        Args:
            name: LLM-generated skill name (e.g., "Track Monthly Expenses")
            description: LLM-generated description of what skill does
            skill_type: Type of skill (tool_workflow, reasoning, hybrid, multi_step)
            original_user_query: The user's original request
            llm_response: The full LLM response that was liked
            workflow_steps: List of steps in the workflow
            tools_used: List of tool names used
            conversation_id: Thread ID where skill was learned
            user_id: User who recorded this skill

        Returns:
            skill_id: Unique identifier for the skill
        """
        skill_id = f"skill_{uuid.uuid4().hex[:12]}"

        # Generate DUAL embeddings for smarter matching
        query_embedding = self._generate_embedding(original_user_query)
        description_embedding = self._generate_embedding(description)

        doc = {
            # Identity
            "skill_id": skill_id,
            "name": name,
            "description": description,
            "skill_type": skill_type,

            # The Workflow
            "original_user_query": original_user_query,
            "llm_response": llm_response,
            "workflow_steps": workflow_steps,
            "tools_used": tools_used,

            # Reasoning/Thinking (Day 5.5 - Chain of Thought)
            "reasoning_steps": reasoning_steps or [],     # Step-by-step thinking
            "reasoning_raw": reasoning_raw or "",         # Raw thinking text

            # DUAL Embeddings for semantic search
            "query_embedding": query_embedding,           # Matches similar user queries
            "description_embedding": description_embedding, # Matches similar intents

            # Provenance - WHERE this skill came from
            "conversation_id": conversation_id,           # Thread/chat where skill was learned
            "user_id": user_id,                           # Who recorded this skill

            # Analytics
            "use_count": 0,
            "success_count": 0,
            "success_rate": 1.0,

            # Timestamps
            "created_at": datetime.utcnow(),
            "last_used_at": None,

            # Status
            "is_active": True,
            "version": 1,
        }

        await self.learned_skills.insert_one(doc)

        print(f"[SkillStore] ✓ Stored new skill: {skill_id}")
        print(f"  → Name: {name}")
        print(f"  → Type: {skill_type}")
        print(f"  → Tools: {tools_used}")
        print(f"  → Conversation: {conversation_id}")
        print(f"  → Query embedding: {'✓' if query_embedding else '✗'}")
        print(f"  → Description embedding: {'✓' if description_embedding else '✗'}")
        print(f"  → Reasoning steps: {len(reasoning_steps) if reasoning_steps else 0}")

        return skill_id

    # ═══════════════════════════════════════════════════════════════════════════
    # SKILL RETRIEVAL (Semantic Search)
    # ═══════════════════════════════════════════════════════════════════════════

    async def find_matching_skills(
        self,
        user_query: str,
        limit: int = 3,
        similarity_threshold: float = 0.70,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Find skills that match the user's query using DUAL embedding search.

        Matches on BOTH:
        1. Query similarity (what user asked before)
        2. Description similarity (what the skill does)

        Returns skills sorted by combined similarity score.
        """
        query_embedding = self._generate_embedding(user_query)
        if not query_embedding:
            print("[SkillStore] Cannot search: embedding generation failed")
            return []

        # Build filter - match all active skills (user_id kept in storage for audit only)
        filter_query = {"is_active": True}

        # Get all active skills
        cursor = self.learned_skills.find(filter_query)
        skills = await cursor.to_list(length=100)

        if not skills:
            return []

        # Calculate combined similarity scores
        scored_skills = []
        for skill in skills:
            query_sim = 0.0
            desc_sim = 0.0

            # Query similarity
            if skill.get("query_embedding"):
                query_sim = self._cosine_similarity(query_embedding, skill["query_embedding"])

            # Description similarity
            if skill.get("description_embedding"):
                desc_sim = self._cosine_similarity(query_embedding, skill["description_embedding"])

            # Combined score: weighted average (query matters more for exact matches)
            combined_score = (query_sim * 0.6) + (desc_sim * 0.4)

            if combined_score >= similarity_threshold:
                skill["query_similarity"] = query_sim
                skill["description_similarity"] = desc_sim
                skill["combined_score"] = combined_score
                scored_skills.append(skill)

        # Sort by combined score
        scored_skills.sort(key=lambda x: x["combined_score"], reverse=True)

        # Return top matches
        results = scored_skills[:limit]

        if results:
            print(f"[SkillStore] Found {len(results)} matching skills")
            for skill in results:
                print(f"  → {skill['name']}: {skill['combined_score']:.3f} (Q:{skill['query_similarity']:.2f}, D:{skill['description_similarity']:.2f})")

        return results

    # ═══════════════════════════════════════════════════════════════════════════
    # SKILL USAGE TRACKING
    # ═══════════════════════════════════════════════════════════════════════════

    async def record_skill_usage(
        self,
        skill_id: str,
        conversation_id: str,
        was_successful: bool = True,
        user_query: str = "",
    ) -> None:
        """Record that a skill was used."""
        # Update skill analytics
        await self.learned_skills.update_one(
            {"skill_id": skill_id},
            {
                "$inc": {
                    "use_count": 1,
                    "success_count": 1 if was_successful else 0,
                },
                "$set": {
                    "last_used_at": datetime.utcnow(),
                }
            }
        )

        # Recalculate success rate
        skill = await self.learned_skills.find_one({"skill_id": skill_id})
        if skill and skill["use_count"] > 0:
            new_rate = skill["success_count"] / skill["use_count"]
            await self.learned_skills.update_one(
                {"skill_id": skill_id},
                {"$set": {"success_rate": new_rate}}
            )

        # Log detailed usage
        await self.skill_usage_analytics.insert_one({
            "skill_id": skill_id,
            "conversation_id": conversation_id,
            "user_query": user_query,
            "was_successful": was_successful,
            "used_at": datetime.utcnow(),
        })

        print(f"[SkillStore] Recorded usage for skill: {skill_id}")

    # ═══════════════════════════════════════════════════════════════════════════
    # SKILL MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    async def get_skill_by_id(self, skill_id: str) -> Optional[Dict]:
        """Get a specific skill by ID."""
        return await self.learned_skills.find_one({"skill_id": skill_id})

    async def get_skills_by_conversation(self, conversation_id: str) -> List[Dict]:
        """Get all skills learned in a specific conversation."""
        cursor = self.learned_skills.find({"conversation_id": conversation_id})
        return await cursor.to_list(length=50)

    async def get_popular_skills(self, limit: int = 10) -> List[Dict]:
        """Get most frequently used skills."""
        cursor = self.learned_skills.find(
            {"is_active": True}
        ).sort("use_count", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def deactivate_skill(self, skill_id: str) -> bool:
        """Deactivate a skill (soft delete)."""
        result = await self.learned_skills.update_one(
            {"skill_id": skill_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0

    async def get_skill_stats(self) -> Dict:
        """Get aggregate statistics about skills."""
        total = await self.learned_skills.count_documents({})
        active = await self.learned_skills.count_documents({"is_active": True})

        # Count by type
        type_counts = {}
        for skill_type in ["tool_workflow", "reasoning", "hybrid", "multi_step"]:
            count = await self.learned_skills.count_documents({"skill_type": skill_type})
            type_counts[skill_type] = count

        # Most used skills
        popular = await self.get_popular_skills(5)

        return {
            "total_skills": total,
            "active_skills": active,
            "skills_by_type": type_counts,
            "most_popular": [
                {"name": s["name"], "use_count": s["use_count"]}
                for s in popular
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

_skill_store: Optional[SkillStore] = None


async def get_skill_store(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "agentic_bot"
) -> SkillStore:
    """Get or create the skill store singleton."""
    global _skill_store

    if _skill_store is None:
        _skill_store = SkillStore(connection_string, database_name)
        await _skill_store.setup()
        print(f"[SkillStore] Connected to MongoDB: {database_name}")

    return _skill_store
