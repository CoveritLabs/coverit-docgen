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

    CREATE INDEX state_session_hash IF NOT EXISTS
    FOR (s:State) ON (s.session_id, s.state_hash);

    CREATE INDEX transition_session_id IF NOT EXISTS
    FOR ()-[t:TRANSITION]-() ON (t.session_id, t.transition_id);
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

GET_BDD_LABELING_STATUS = """
CALL () {
  MATCH (state:State {session_id: $session_id})
  RETURN count(state) AS state_count,
         sum(CASE
           WHEN state.labeling_status IS NULL
             OR state.labeling_status = 'PENDING'
           THEN 1 ELSE 0
         END) AS pending_states,
         sum(CASE
           WHEN state.labeling_status = 'QUEUED'
           THEN 1 ELSE 0
         END) AS queued_states,
         sum(CASE
           WHEN state.labeling_status IS NOT NULL
             AND NOT (
               state.labeling_status IN ['PENDING', 'QUEUED', 'COMPLETED']
             )
           THEN 1 ELSE 0
         END) AS invalid_states
}
CALL () {
  MATCH (from:State {session_id: $session_id})
        -[transition:TRANSITION]->
        (to:State {session_id: $session_id})
  RETURN count(transition) AS transition_count,
         sum(CASE
           WHEN transition.labeling_status IS NULL
             OR transition.labeling_status = 'PENDING'
           THEN 1 ELSE 0
         END) AS pending_transitions,
         sum(CASE
           WHEN transition.labeling_status = 'QUEUED'
           THEN 1 ELSE 0
         END) AS queued_transitions,
         sum(CASE
           WHEN transition.labeling_status IS NOT NULL
             AND NOT (
               transition.labeling_status IN [
                 'PENDING', 'QUEUED', 'COMPLETED'
               ]
             )
           THEN 1 ELSE 0
         END) AS invalid_transitions
}
RETURN state_count,
       transition_count,
       pending_states,
       pending_transitions,
       queued_states,
       queued_transitions,
       invalid_states,
       invalid_transitions
"""

CLAIM_BDD_SESSION_LABELING = """
CALL () {
  MATCH (state:State {session_id: $session_id})
  WHERE state.labeling_status IS NULL
     OR state.labeling_status = 'PENDING'
  SET state.labeling_status = 'QUEUED',
      state.labeling_claim_id = $claim_id
  RETURN collect(elementId(state)) AS state_ids
}
CALL () {
  MATCH (from:State {session_id: $session_id})
        -[transition:TRANSITION]->
        (to:State {session_id: $session_id})
  WHERE transition.labeling_status IS NULL
     OR transition.labeling_status = 'PENDING'
  SET transition.labeling_status = 'QUEUED',
      transition.labeling_claim_id = $claim_id
  RETURN collect(elementId(transition)) AS transition_ids
}
RETURN state_ids, transition_ids
"""

RESOLVE_BDD_FLOWS = """
UNWIND $flows AS flow
OPTIONAL MATCH (checkpoint:State {
  session_id: $session_id,
  state_hash: flow.checkpoint_hash
})
UNWIND range(0, size(flow.transition_ids) - 1) AS transition_index
WITH flow,
     checkpoint,
     transition_index,
     flow.transition_ids[transition_index] AS requested_transition_id
OPTIONAL MATCH (from:State {session_id: $session_id})
      -[transition:TRANSITION {
        session_id: $session_id,
        transition_id: requested_transition_id
      }]->
      (to:State {session_id: $session_id})
RETURN flow.flow_index AS flow_index,
       transition_index,
       elementId(checkpoint) AS checkpoint_db_id,
       checkpoint.state_hash AS checkpoint_hash,
       checkpoint.name AS checkpoint_name,
       checkpoint.description AS checkpoint_description,
       checkpoint.url AS checkpoint_url,
       checkpoint.labeling_status AS checkpoint_status,
       elementId(transition) AS transition_db_id,
       transition.transition_id AS transition_id,
       transition.name AS transition_name,
       transition.action AS transition_action,
       transition.action_type AS action_type,
       transition.locator_value AS locator_value,
       transition.labeling_status AS transition_status,
       elementId(from) AS from_db_id,
       from.state_hash AS from_hash,
       from.name AS from_name,
       from.description AS from_description,
       from.url AS from_url,
       from.labeling_status AS from_status,
       elementId(to) AS to_db_id,
       to.state_hash AS to_hash,
       to.name AS to_name,
       to.description AS to_description,
       to.url AS to_url,
       to.labeling_status AS to_status
ORDER BY flow_index, transition_index
"""

GET_BDD_OUTGOING_LOCATORS = """
UNWIND $state_hashes AS state_hash
MATCH (state:State {session_id: $session_id, state_hash: state_hash})
OPTIONAL MATCH (state)-[transition:TRANSITION]->
               (:State {session_id: $session_id})
WITH state_hash,
     [
       locator IN collect(DISTINCT transition.locator_value)
       WHERE locator IS NOT NULL AND trim(locator) <> ''
     ] AS locators
RETURN state_hash, locators
"""
