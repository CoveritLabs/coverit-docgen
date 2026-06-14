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
WITH s LIMIT 100             
SET s.labeling_status = 'QUEUED'
RETURN elementId(s) AS id
"""

GET_UNLABELED_TRANSITIONS = """
MATCH ()-[t:TRANSITION]->()
WHERE t.labeling_status IS NULL OR t.labeling_status = 'PENDING'
WITH t LIMIT 100
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