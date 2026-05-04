"""
Improvement Store
=================
MongoDB storage for lessons learned, improvements, and patterns.

Collections:
- error_lessons: What went wrong and how to fix
- prompt_improvements: Better prompts discovered
- success_patterns: What worked well

Clean structure for easy understanding.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorClient


class LessonType(str, Enum):
    """Types of lessons the agent can learn."""
    ERROR_RECOVERY = "error_recovery"      # How to recover from errors
    PROMPT_IMPROVEMENT = "prompt_improvement"  # Better way to prompt
    TOOL_USAGE = "tool_usage"              # Better tool usage patterns
    USER_PREFERENCE = "user_preference"    # What user prefers
    SUCCESS_PATTERN = "success_pattern"    # What worked well


@dataclass
class Lesson:
    """A lesson learned by the agent."""
    id: str
    lesson_type: LessonType
    context: str                    # What was the situation
    original_action: Dict[str, Any] # What agent did
    outcome: str                    # What happened
    lesson_learned: str             # What to do differently
    improved_approach: str          # The better way
    confidence: float = 0.5         # How confident (0-1)
    usage_count: int = 0            # Times this lesson was applied
    success_rate: float = 0.0       # Success rate when applied
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)


class ImprovementStore:
    """
    MongoDB store for agent's learned improvements.

    Provides:
    - Store lessons from failures
    - Retrieve relevant lessons for new tasks
    - Track lesson effectiveness
    - Prune ineffective lessons
    """

    def __init__(
        self,
        connection_string: str = "mongodb://localhost:27017",
        database_name: str = "agentic_bot",
    ):
        self.client = AsyncIOMotorClient(connection_string)
        self.db = self.client[database_name]

        # Collections for different types of improvements
        self.error_lessons = self.db["error_lessons"]
        self.prompt_improvements = self.db["prompt_improvements"]
        self.success_patterns = self.db["success_patterns"]

        # Embedding model for semantic search (lazy loaded)
        self._embedding_model = None
        print("[ImprovementStore] Initialized (embedding model will load on first use)")

    async def setup(self) -> None:
        """Create indexes for efficient queries."""
        # Error lessons indexes
        await self.error_lessons.create_index([("lesson_type", 1)])
        await self.error_lessons.create_index([("tags", 1)])
        await self.error_lessons.create_index([("confidence", -1)])
        await self.error_lessons.create_index([
            ("context", "text"),
            ("lesson_learned", "text"),
        ])

        # Prompt improvements indexes
        await self.prompt_improvements.create_index([("task_type", 1)])
        await self.prompt_improvements.create_index([("success_rate", -1)])

        # Success patterns indexes
        await self.success_patterns.create_index([("pattern_type", 1)])
        await self.success_patterns.create_index([("usage_count", -1)])

        print("[ImprovementStore] MongoDB indexes created")

    # ═══════════════════════════════════════════════════════════════════════
    # ERROR LESSONS
    # ═══════════════════════════════════════════════════════════════════════

    async def store_error_lesson(
        self,
        error_type: str,
        context: str,
        original_action: Dict[str, Any],
        error_message: str,
        lesson_learned: str,
        improved_approach: str,
        tags: List[str] = None,
    ) -> str:
        """
        Store a lesson learned from an error.

        Args:
            error_type: Category of error (tool_failure, invalid_response, etc.)
            context: What was the agent trying to do
            original_action: The action that failed
            error_message: The error that occurred
            lesson_learned: What the agent learned
            improved_approach: How to do it better next time
            tags: Searchable tags

        Returns:
            Lesson ID
        """
        import uuid
        lesson_id = f"lesson_{uuid.uuid4().hex[:12]}"

        doc = {
            "id": lesson_id,
            "lesson_type": LessonType.ERROR_RECOVERY.value,
            "error_type": error_type,
            "context": context,
            "original_action": original_action,
            "error_message": error_message,
            "lesson_learned": lesson_learned,
            "improved_approach": improved_approach,
            "confidence": 0.5,  # Initial confidence
            "usage_count": 0,
            "success_rate": 0.0,
            "created_at": datetime.utcnow(),
            "last_used": None,
            "tags": tags or [error_type],
        }

        await self.error_lessons.insert_one(doc)
        print(f"[ImprovementStore] Stored error lesson: {lesson_id}")
        return lesson_id

    async def find_relevant_lessons(
        self,
        context: str,
        error_type: str = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Find lessons relevant to current context.

        Uses text search and error type matching.
        """
        query = {}

        if error_type:
            query["error_type"] = error_type

        # Try text search first
        if context:
            query["$text"] = {"$search": context}

        cursor = self.error_lessons.find(query).sort([
            ("confidence", -1),
            ("success_rate", -1),
        ]).limit(limit)

        lessons = []
        async for doc in cursor:
            lessons.append(doc)

        # Fallback: if no text matches, get recent high-confidence lessons
        if not lessons and error_type:
            cursor = self.error_lessons.find(
                {"error_type": error_type}
            ).sort("confidence", -1).limit(limit)

            async for doc in cursor:
                lessons.append(doc)

        return lessons

    async def update_lesson_effectiveness(
        self,
        lesson_id: str,
        was_successful: bool,
    ) -> None:
        """
        Update lesson effectiveness after it was applied.

        Increases confidence if successful, decreases if not.
        """
        lesson = await self.error_lessons.find_one({"id": lesson_id})
        if not lesson:
            return

        usage_count = lesson.get("usage_count", 0) + 1
        current_successes = lesson.get("success_rate", 0) * lesson.get("usage_count", 0)

        if was_successful:
            new_successes = current_successes + 1
            confidence_delta = 0.1
        else:
            new_successes = current_successes
            confidence_delta = -0.1

        new_success_rate = new_successes / usage_count
        new_confidence = min(1.0, max(0.1, lesson.get("confidence", 0.5) + confidence_delta))

        await self.error_lessons.update_one(
            {"id": lesson_id},
            {
                "$set": {
                    "usage_count": usage_count,
                    "success_rate": new_success_rate,
                    "confidence": new_confidence,
                    "last_used": datetime.utcnow(),
                }
            }
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PROMPT IMPROVEMENTS
    # ═══════════════════════════════════════════════════════════════════════

    async def store_prompt_improvement(
        self,
        task_type: str,
        original_prompt: str,
        improved_prompt: str,
        improvement_reason: str,
        user_feedback: str = None,
    ) -> str:
        """Store a discovered prompt improvement (legacy method)."""
        import uuid
        improvement_id = f"prompt_{uuid.uuid4().hex[:12]}"

        doc = {
            "id": improvement_id,
            "task_type": task_type,
            "original_prompt": original_prompt,
            "improved_prompt": improved_prompt,
            "improvement_reason": improvement_reason,
            "user_feedback": user_feedback,
            "usage_count": 0,
            "success_rate": 0.0,
            "created_at": datetime.utcnow(),
        }

        await self.prompt_improvements.insert_one(doc)
        print(f"[ImprovementStore] Stored prompt improvement: {improvement_id}")
        return improvement_id

    async def store_feedback_improvement(
        self,
        original_user_prompt: str,
        original_llm_response: str,
        user_negative_feedback: str,
        improved_llm_response: str,
        context_keywords: List[str],
        thread_id: str,  # Thread-specific learning
        feedback_type: str = "negative",
        issues_detected: List[str] = None,
        key_correction: str = None,  # NEW: Direct fact to apply
    ) -> str:
        """
        Store a complete feedback-based improvement.

        This captures the full learning cycle:
        1. User asked something (original_user_prompt)
        2. LLM responded (original_llm_response)
        3. User gave negative feedback (user_negative_feedback)
        4. LLM generated improved response (improved_llm_response)
        5. Key correction extracted (key_correction) - the single most important fact

        Args:
            original_user_prompt: The original user question/request
            original_llm_response: LLM's first response that user disliked
            user_negative_feedback: User's negative feedback message
            improved_llm_response: LLM's corrected/improved response
            context_keywords: Keywords for retrieval (e.g., ["expense", "add", "date"])
            thread_id: Conversation thread ID (scopes learning to specific conversation)
            feedback_type: Type of feedback (negative, correction, clarification)
            issues_detected: List of issues found (e.g., ["wrong_format", "missing_info"])
            key_correction: The single most important corrected fact (e.g., "User's name is Mansingh")

        Returns:
            Improvement ID
        """
        import uuid
        improvement_id = f"fb_{uuid.uuid4().hex[:12]}"

        # Generate embedding for semantic search
        embedding = self._generate_embedding(original_user_prompt)

        doc = {
            "id": improvement_id,
            "feedback_type": feedback_type,

            # The learning cycle
            "original_user_prompt": original_user_prompt,
            "original_llm_response": original_llm_response,
            "user_negative_feedback": user_negative_feedback,
            "improved_llm_response": improved_llm_response,

            # NEW: Key correction - direct fact for immediate application
            "key_correction": key_correction or "",

            # For retrieval
            "context_keywords": context_keywords,
            "issues_detected": issues_detected or [],

            # Thread-scoped learning
            "thread_id": thread_id,

            # Semantic search via embeddings
            "embedding": embedding,  # 384-dim vector or None

            # Tracking
            "usage_count": 0,
            "success_count": 0,
            "success_rate": 0.0,
            "confidence": 0.5,
            "created_at": datetime.utcnow(),
            "last_applied": None,
        }

        await self.prompt_improvements.insert_one(doc)
        print(f"[ImprovementStore] Stored feedback improvement: {improvement_id}")
        print(f"  → Thread: {thread_id}")
        print(f"  → Original: {original_user_prompt[:50]}...")
        print(f"  → Key correction: {key_correction or 'None'}")
        print(f"  → Embedding: {'✓ Generated' if embedding else '✗ Failed'}")
        return improvement_id

    async def find_relevant_improvements(
        self,
        user_prompt: str,
        thread_id: str,  # NEW: Required for thread-scoped learning
        limit: int = 3,
        similarity_threshold: float = 0.4,  # Minimum cosine similarity
    ) -> List[Dict[str, Any]]:
        """
        Find improvements relevant to the current user prompt using semantic search.

        SUPERHUMAN FEATURES:
        1. Thread-scoped: Only retrieves feedback from same conversation
        2. Semantic similarity: Uses embeddings for contextual matching
        3. Temporal decay: Recent feedback prioritized but old never forgotten
        
        Args:
            user_prompt: Current user question/request
            thread_id: Conversation thread ID (filters to same conversation)
            limit: Maximum number of improvements to return
            similarity_threshold: Minimum cosine similarity (0-1) to include result
            
        Returns:
            List of improvements, ranked by: similarity * temporal_decay
        """
        print(f"[ImprovementStore] Finding improvements for thread: {thread_id}")
        
        # Generate embedding for query
        query_embedding = self._generate_embedding(user_prompt)
        
        # Fetch all improvements from THIS thread only
        cursor = self.prompt_improvements.find({"thread_id": thread_id})
        
        candidates = []
        async for doc in cursor:
            # Convert ObjectId to string for JSON serialization
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            candidates.append(doc)
        
        if not candidates:
            print(f"[ImprovementStore] No improvements found for thread {thread_id}")
            return []
        
        print(f"[ImprovementStore] Found {len(candidates)} candidate improvements in thread")
        
        # If embeddings available, use semantic search
        if query_embedding and self.embedding_model:
            scored_improvements = []
            
            for imp in candidates:
                imp_embedding = imp.get("embedding")
                
                if not imp_embedding:
                    # Fallback: use keyword matching
                    keywords = self._extract_keywords(user_prompt)
                    imp_keywords = imp.get("context_keywords", [])
                    
                    # Simple keyword overlap score
                    overlap = len(set(keywords) & set(imp_keywords))
                    similarity = overlap / max(len(keywords), 1) if keywords else 0
                else:
                    # Compute cosine similarity
                    similarity = self._cosine_similarity(query_embedding, imp_embedding)
                
                # Apply temporal decay
                created_at = imp.get("created_at")
                if created_at:
                    decay = self._compute_temporal_decay(created_at)
                else:
                    decay = 0.5  # Default if no timestamp
                
                # Final score = similarity * decay
                final_score = similarity * decay
                
                # Filter by threshold
                if final_score >= similarity_threshold:
                    imp["similarity"] = similarity
                    imp["temporal_decay"] = decay
                    imp["final_score"] = final_score
                    scored_improvements.append(imp)
            
            # Sort by final score DESC
            scored_improvements.sort(key=lambda x: x["final_score"], reverse=True)
            
            # Return top N
            results = scored_improvements[:limit]
            
            print(f"[ImprovementStore] Returning {len(results)} improvements (semantic search)")
            for i, imp in enumerate(results):
                print(f"  {i+1}. Score: {imp['final_score']:.3f} (sim={imp['similarity']:.3f}, decay={imp['temporal_decay']:.3f})")
            
            return results
        
        # Fallback: keyword-based matching (if embeddings failed)
        print("[ImprovementStore] Embeddings unavailable, using keyword fallback")
        keywords = self._extract_keywords(user_prompt)
        
        if not keywords:
            # Last resort: return most recent improvements
            results = sorted(candidates, key=lambda x: x.get("created_at", datetime.min), reverse=True)[:limit]
            return results
        
        # Keyword match
        scored_improvements = []
        for imp in candidates:
            imp_keywords = imp.get("context_keywords", [])
            overlap = len(set(keywords) & set(imp_keywords))
            
            if overlap > 0:
                # Apply temporal decay for ranking
                created_at = imp.get("created_at")
                decay = self._compute_temporal_decay(created_at) if created_at else 0.5
                
                imp["keyword_score"] = overlap
                imp["temporal_decay"] = decay
                imp["final_score"] = overlap * decay
                scored_improvements.append(imp)
        
        scored_improvements.sort(key=lambda x: x["final_score"], reverse=True)
        return scored_improvements[:limit]

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords from text for matching."""
        text_lower = text.lower()

        # Action keywords
        action_keywords = [
            "add", "create", "insert", "save", "store",
            "list", "show", "get", "fetch", "find", "search",
            "delete", "remove", "update", "edit", "modify",
            "summarize", "calculate", "total", "sum",
            "expense", "category", "date", "amount",
        ]

        found = []
        for keyword in action_keywords:
            if keyword in text_lower:
                found.append(keyword)

        return found

    async def get_improved_prompt(
        self,
        task_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the best improved prompt for a task type."""
        doc = await self.prompt_improvements.find_one(
            {"task_type": task_type},
            sort=[("success_rate", -1), ("usage_count", -1)]
        )
        return doc

    async def update_improvement_effectiveness(
        self,
        improvement_id: str,
        was_successful: bool,
    ) -> None:
        """Update how effective an improvement was when applied."""
        improvement = await self.prompt_improvements.find_one({"id": improvement_id})
        if not improvement:
            return

        usage_count = improvement.get("usage_count", 0) + 1
        success_count = improvement.get("success_count", 0)

        if was_successful:
            success_count += 1
            confidence_delta = 0.1
        else:
            confidence_delta = -0.1

        new_success_rate = success_count / usage_count if usage_count > 0 else 0
        new_confidence = min(1.0, max(0.1, improvement.get("confidence", 0.5) + confidence_delta))

        await self.prompt_improvements.update_one(
            {"id": improvement_id},
            {
                "$set": {
                    "usage_count": usage_count,
                    "success_count": success_count,
                    "success_rate": new_success_rate,
                    "confidence": new_confidence,
                    "last_applied": datetime.utcnow(),
                }
            }
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SUCCESS PATTERNS
    # ═══════════════════════════════════════════════════════════════════════

    async def store_success_pattern(
        self,
        pattern_type: str,
        description: str,
        actions: List[Dict[str, Any]],
        context: str,
        outcome: str,
    ) -> str:
        """Store a successful pattern for future use."""
        import uuid
        pattern_id = f"pattern_{uuid.uuid4().hex[:12]}"

        doc = {
            "id": pattern_id,
            "pattern_type": pattern_type,
            "description": description,
            "actions": actions,
            "context": context,
            "outcome": outcome,
            "usage_count": 1,
            "created_at": datetime.utcnow(),
            "last_used": datetime.utcnow(),
        }

        await self.success_patterns.insert_one(doc)
        print(f"[ImprovementStore] Stored success pattern: {pattern_id}")
        return pattern_id

    async def find_success_patterns(
        self,
        pattern_type: str = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find successful patterns."""
        query = {}
        if pattern_type:
            query["pattern_type"] = pattern_type

        cursor = self.success_patterns.find(query).sort(
            "usage_count", -1
        ).limit(limit)

        patterns = []
        async for doc in cursor:
            patterns.append(doc)

        return patterns

    # ═══════════════════════════════════════════════════════════════════════
    # EMBEDDING & SEMANTIC SEARCH HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    @property
    def embedding_model(self):
        """Lazy load embedding model on first use."""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                print("[ImprovementStore] Loading embedding model: all-MiniLM-L6-v2...")
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                print("[ImprovementStore] Embedding model loaded successfully (384 dimensions)")
            except Exception as e:
                print(f"[ImprovementStore] ERROR loading embedding model: {e}")
                # Fallback: return None to disable embeddings
                return None
        return self._embedding_model

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding vector for text using sentence-transformers.
        
        Returns 384-dimensional vector or None if model failed to load.
        """
        if not text or not text.strip():
            return None
            
        try:
            if self.embedding_model is None:
                return None
            embedding = self.embedding_model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            print(f"[ImprovementStore] Error generating embedding: {e}")
            return None

    def _compute_temporal_decay(self, created_at: datetime) -> float:
        """
        Compute temporal decay factor based on age.
        
        Recent feedback = higher weight (superhuman: never forgets, but prioritizes recent)
        
        Formula: decay = 1.0 / (1 + age_days / 30)
        - 1 day old: 0.97 (97%)
        - 20 days old: 0.6 (60%)
        - 100 days old: 0.23 (23%)
        
        Returns:
            Float between 0.0 and 1.0
        """
        age = datetime.utcnow() - created_at
        age_days = age.days + (age.seconds / 86400.0)  # Include fractional days
        
        # 30-day half-life
        decay_factor = 1.0 / (1 + age_days / 30.0)
        return decay_factor

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Compute cosine similarity between two vectors.
        
        Returns value between -1 and 1 (typically 0 to 1 for semantic similarity).
        """
        if not vec1 or not vec2:
            return 0.0
        
        import numpy as np
        
        try:
            v1 = np.array(vec1)
            v2 = np.array(vec2)
            
            # Compute dot product
            dot_product = np.dot(v1, v2)
            
            # Compute magnitudes
            norm_v1 = np.linalg.norm(v1)
            norm_v2 = np.linalg.norm(v2)
            
            # Avoid division by zero
            if norm_v1 == 0 or norm_v2 == 0:
                return 0.0
            
            similarity = dot_product / (norm_v1 * norm_v2)
            return float(similarity)
        except Exception as e:
            print(f"[ImprovementStore] Error computing similarity: {e}")
            return 0.0

    # ═══════════════════════════════════════════════════════════════════════
    # STATISTICS
    # ═══════════════════════════════════════════════════════════════════════

    async def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about agent's learning."""
        error_count = await self.error_lessons.count_documents({})
        prompt_count = await self.prompt_improvements.count_documents({})
        pattern_count = await self.success_patterns.count_documents({})

        # Get average success rate of lessons
        pipeline = [
            {"$group": {
                "_id": None,
                "avg_confidence": {"$avg": "$confidence"},
                "avg_success_rate": {"$avg": "$success_rate"},
                "total_usage": {"$sum": "$usage_count"},
            }}
        ]

        stats_cursor = self.error_lessons.aggregate(pipeline)
        lesson_stats = await stats_cursor.to_list(1)

        return {
            "total_lessons": error_count,
            "total_prompt_improvements": prompt_count,
            "total_success_patterns": pattern_count,
            "lesson_stats": lesson_stats[0] if lesson_stats else {},
        }


# Singleton
_improvement_store: Optional[ImprovementStore] = None


async def get_improvement_store(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database",
) -> ImprovementStore:
    """Get or create improvement store instance."""
    global _improvement_store

    if _improvement_store is None:
        _improvement_store = ImprovementStore(connection_string, database_name)
        await _improvement_store.setup()
        print(f"[ImprovementStore] Connected to MongoDB: {database_name}")

    return _improvement_store
