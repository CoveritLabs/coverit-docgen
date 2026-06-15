"""Cypher statements used by the incremental labeling pipeline.

Recommended Neo4j indexes for production deployments::

    CREATE INDEX state_session_id IF NOT EXISTS
    FOR (s:State) ON (s.session_id);

    CREATE INDEX state_labeling_status IF NOT EXISTS
    FOR (s:State) ON (s.labeling_status);

    CREATE INDEX state_session_status IF NOT EXISTS
    FOR (s:State) ON (s.session_id, s.labeling_status);

    CREATE INDEX transition_labeling_status IF NOT EXISTS
    FOR ()-[t:TRANSITION]-() ON (t.labeling_status);
"""

GET_STATE = """
MATCH (s:State)
WHERE elementId(s) = $id
RETURN s
"""

GET_TRANSITION = """
MATCH (from:State)-[t:TRANSITION]->(to:State)
WHERE elementId(t) = $id
RETURN elementId(from) AS from_id,
       elementId(to) AS to_id,
       t.locator_value AS locator,
       from.session_id AS session_id,
       to.session_id AS to_session_id
"""

UPDATE_SINGLE_STATE = """
MATCH (s:State)
WHERE elementId(s) = $id
  AND s.labeling_status = 'QUEUED'
SET s.name = $name,
    s.description = $description,
    s.labeling_status = 'COMPLETED'
REMOVE s.labeling_claim_id
"""

UPDATE_SINGLE_TRANSITION = """
MATCH ()-[t:TRANSITION]->()
WHERE elementId(t) = $id
  AND t.labeling_status = 'QUEUED'
SET t.name = $name,
    t.action = $action,
    t.labeling_status = 'COMPLETED'
REMOVE t.labeling_claim_id
"""

SET_STATE_PENDING = """
MATCH (s:State)
WHERE elementId(s) = $id
  AND s.labeling_status = 'QUEUED'
SET s.labeling_status = 'PENDING'
REMOVE s.labeling_claim_id
"""

SET_TRANSITION_PENDING = """
MATCH ()-[t:TRANSITION]->()
WHERE elementId(t) = $id
  AND t.labeling_status = 'QUEUED'
SET t.labeling_status = 'PENDING'
REMOVE t.labeling_claim_id
"""

CLAIM_UNLABELED_SESSIONS = """
MATCH (candidate:State)
WHERE candidate.session_id IS NOT NULL
  AND (
    candidate.labeling_status IS NULL
    OR candidate.labeling_status = 'PENDING'
    OR EXISTS {
      MATCH (candidate)-[candidate_transition:TRANSITION]->(
        :State {session_id: candidate.session_id}
      )
      WHERE candidate_transition.labeling_status IS NULL
         OR candidate_transition.labeling_status = 'PENDING'
    }
  )
WITH DISTINCT candidate.session_id AS session_id
LIMIT 10

CALL (session_id) {
  OPTIONAL MATCH (state:State {session_id: session_id})
  WHERE state.labeling_status IS NULL
     OR state.labeling_status = 'PENDING'
  WITH collect(state) AS states
  FOREACH (
    state IN states |
    SET state.labeling_claim_id = CASE
          WHEN state.labeling_status IS NULL
            OR state.labeling_status = 'PENDING'
          THEN $claim_id
          ELSE state.labeling_claim_id
        END,
        state.labeling_status = CASE
          WHEN state.labeling_status IS NULL
            OR state.labeling_status = 'PENDING'
          THEN 'QUEUED'
          ELSE state.labeling_status
        END
  )
  RETURN [
    state IN states
    WHERE state.labeling_claim_id = $claim_id |
    elementId(state)
  ] AS state_ids
}

CALL (session_id) {
  OPTIONAL MATCH (from:State {session_id: session_id})
        -[transition:TRANSITION]->
        (to:State {session_id: session_id})
  WHERE transition.labeling_status IS NULL
     OR transition.labeling_status = 'PENDING'
  WITH collect(transition) AS transitions
  FOREACH (
    transition IN transitions |
    SET transition.labeling_claim_id = CASE
          WHEN transition.labeling_status IS NULL
            OR transition.labeling_status = 'PENDING'
          THEN $claim_id
          ELSE transition.labeling_claim_id
        END,
        transition.labeling_status = CASE
          WHEN transition.labeling_status IS NULL
            OR transition.labeling_status = 'PENDING'
          THEN 'QUEUED'
          ELSE transition.labeling_status
        END
  )
  RETURN [
    transition IN transitions
    WHERE transition.labeling_claim_id = $claim_id |
    elementId(transition)
  ] AS transition_ids
}

WITH session_id, state_ids, transition_ids
WHERE size(state_ids) > 0 OR size(transition_ids) > 0
RETURN session_id AS id, state_ids, transition_ids
"""

GET_QUEUED_SESSION_STATES = """
MATCH (s:State {session_id: $session_id})
WHERE s.labeling_status = 'QUEUED'
RETURN elementId(s) AS id, s.url AS url, s.html AS html
"""

GET_QUEUED_SESSION_TRANSITIONS = """
MATCH (from:State {session_id: $session_id})
      -[t:TRANSITION]->
      (to:State {session_id: $session_id})
WHERE t.labeling_status = 'QUEUED'
RETURN elementId(t) AS id,
       elementId(from) AS from_id,
       elementId(to) AS to_id,
       t.locator_value AS locator,
       from.html AS from_html,
       from.url AS from_url
"""

ROLLBACK_CLAIMED_ITEMS = """
UNWIND CASE
  WHEN size($state_ids) = 0 THEN [null]
  ELSE $state_ids
END AS state_id
OPTIONAL MATCH (state:State {session_id: $session_id})
WHERE elementId(state) = state_id
  AND state.labeling_status = 'QUEUED'
SET state.labeling_status = 'PENDING'
REMOVE state.labeling_claim_id

WITH count(state) AS state_count
UNWIND CASE
  WHEN size($transition_ids) = 0 THEN [null]
  ELSE $transition_ids
END AS transition_id
OPTIONAL MATCH (from:State {session_id: $session_id})
      -[transition:TRANSITION]->
      (to:State {session_id: $session_id})
WHERE elementId(transition) = transition_id
  AND transition.labeling_status = 'QUEUED'
SET transition.labeling_status = 'PENDING'
REMOVE transition.labeling_claim_id
RETURN state_count, count(transition) AS transition_count
"""
