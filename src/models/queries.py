GET_STATE = """
MATCH (s:State) 
WHERE elementId(s) = $id 
RETURN s
"""

GET_TRANSITION = """
MATCH (from:State)-[t:TRANSITION]->(to:State)
WHERE elementId(t) = $id
RETURN elementId(from) AS from_id, elementId(to) AS to_id, t.locator_value AS locator
"""

GET_SESSION_STATES = """
MATCH (s:State {session_id: $session_id}) 
RETURN s
"""

GET_SESSION_TRANSITIONS = """
MATCH (from:State {session_id: $session_id})-[t:TRANSITION]->(to:State {session_id: $session_id})
RETURN elementId(t) AS id, elementId(from) AS from_id, elementId(to) AS to_id, t.locator_value AS locator
"""

UPDATE_STATES = """
UNWIND $updates AS row
MATCH (n)
WHERE elementId(n) = row.id
SET n += row.props
"""

UPDATE_TRANSITIONS = """
UNWIND $updates AS row
MATCH ()-[r]->()
WHERE elementId(r) = row.id
SET r += row.props
"""

UPDATE_SINGLE_STATE = """
MATCH (s:State)
WHERE elementId(s) = $id
SET s.name = $name,
    s.description = $description,
    s.labeling_status = 'COMPLETED'
"""

UPDATE_SINGLE_TRANSITION = """
MATCH ()-[t:TRANSITION]->()
WHERE elementId(t) = $id
SET t.name = $name,
    t.action = $action,
    t.labeling_status = 'COMPLETED'
"""

GET_UNLABELED_STATES = """
MATCH (s:State)
WHERE s.labeling_status IS NULL OR s.labeling_status = 'PENDING'
SET s.labeling_status = 'QUEUED'
RETURN elementId(s) AS id
"""

GET_UNLABELED_TRANSITIONS = """
MATCH ()-[t:TRANSITION]->()
WHERE t.labeling_status IS NULL OR t.labeling_status = 'PENDING'
SET t.labeling_status = 'QUEUED'
RETURN elementId(t) AS id
"""

SET_STATE_PENDING = """
MATCH (s:State)
WHERE elementId(s) = $id
SET s.labeling_status = 'PENDING'
"""

SET_TRANSITION_PENDING = """
MATCH ()-[t:TRANSITION]->()
WHERE elementId(t) = $id
SET t.labeling_status = 'PENDING'
"""

GET_UNLABELED_SESSIONS = """
MATCH (s:State)
OPTIONAL MATCH (s)-[t:TRANSITION]->()
WITH s, t
WHERE (s.labeling_status IS NULL OR s.labeling_status = 'PENDING')
   OR (t IS NOT NULL AND (t.labeling_status IS NULL OR t.labeling_status = 'PENDING'))
WITH DISTINCT s.session_id AS sess_id LIMIT 50

OPTIONAL MATCH (pending_state:State {session_id: sess_id})
WHERE pending_state.labeling_status IS NULL OR pending_state.labeling_status = 'PENDING'
SET pending_state.labeling_status = 'QUEUED'

WITH DISTINCT sess_id

OPTIONAL MATCH (:State {session_id: sess_id})-[pending_trans:TRANSITION]->()
WHERE pending_trans.labeling_status IS NULL OR pending_trans.labeling_status = 'PENDING'
SET pending_trans.labeling_status = 'QUEUED'

RETURN DISTINCT sess_id AS id
"""

GET_UNLABELED_SESSION_STATES = """
MATCH (s:State {session_id: $session_id})
WHERE s.labeling_status = 'QUEUED'
RETURN elementId(s) AS id, s.url AS url, s.html AS html
"""

GET_UNLABELED_SESSION_TRANSITIONS = """
MATCH (from:State)-[t:TRANSITION]->(to:State {session_id: $session_id})
WHERE t.labeling_status = 'QUEUED'

RETURN elementId(t) AS id, elementId(from) AS from_id, elementId(to) AS to_id, t.locator_value AS locator, from.html AS from_html, from.url AS from_url
"""

SET_SESSION_PENDING = """
OPTIONAL MATCH (s:State {session_id: $session_id})
WHERE s.labeling_status = 'QUEUED'
SET s.labeling_status = 'PENDING'

WITH count(s) AS dummy
OPTIONAL MATCH (:State)-[t:TRANSITION]->(:State {session_id: $session_id})
WHERE t.labeling_status = 'QUEUED'
SET t.labeling_status = 'PENDING'
"""
