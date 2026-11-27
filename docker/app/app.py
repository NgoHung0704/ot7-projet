"""Impact Duel: the player guesses whether a simulated asteroid impact or a real disaster was worse.

The score lives only in the browser session: rounds are not written back to the warehouse.
"""

import pandas as pd
import psycopg
import streamlit as st

import game_data
from duel import ASTEROID, DISASTER, ROUNDS_PER_GAME, dollars, estimate, find_duel, people, score, worse

DRAW_ATTEMPTS = 5
PIPELINE_HINT = "Run the Airflow DAGs `ingest_raw`, `staging`, `simulation` and `game_views` first."

st.set_page_config(page_title="Impact Duel", page_icon="☄️")


def new_game() -> None:
    st.session_state.update(round_number=1, points=0, questions=0, duel=None, picks=None,
                            played_asteroids=set(), played_disasters=set())


def draw_duel(conn):
    for _ in range(DRAW_ATTEMPTS):
        duel = find_duel(game_data.shuffled_scenarios(conn), game_data.shuffled_disasters(conn),
                         st.session_state.played_asteroids, st.session_state.played_disasters)
        if duel:
            st.session_state.played_asteroids.add(duel.asteroid["des"])
            st.session_state.played_disasters.add(duel.disaster["dis_no"])
            return duel
    return None


def disaster_title(disaster: dict) -> str:
    return disaster["event_name"] or f"{disaster['disaster_type']} in {disaster['country']}"


def show_asteroid(asteroid: dict) -> None:
    st.subheader(f"☄️ {asteroid['asteroid_name']}")
    st.write(f"Strikes **{asteroid['city']}**, {asteroid['country']}")
    st.caption(f"{asteroid['diameter_m']:,.0f} m wide · {asteroid['entry_speed_kms']:.1f} km/s · "
               f"city of {people(asteroid['population'] or 0)} people")
    st.map(pd.DataFrame([{"lat": asteroid["latitude"], "lon": asteroid["longitude"]}]), zoom=3, size=80000,
           height=250)


def show_disaster(disaster: dict) -> None:
    st.subheader(f"🌋 {disaster_title(disaster)}")
    st.write(f"**{disaster['disaster_type']}**, {disaster['country']}, {disaster['year']}")


def ask(question: str, key: str) -> str | None:
    return st.radio(question, [ASTEROID, DISASTER], index=None, horizontal=True, key=key)


def show_answer(label: str, pick: str, asteroid_value: int, disaster_value: int, display) -> None:
    mark = "✅" if pick == worse(asteroid_value, disaster_value) else "❌"
    answer = (f"{mark} **{label}**: asteroid ≈ {display(estimate(asteroid_value))} (estimate) · "
              f"disaster {display(disaster_value)}")
    # Markdown reads a pair of $ as a LaTeX formula.
    st.write(answer.replace("$", "\\$"))


def show_similar_events(conn, asteroid: dict, excluded_dis_no: str) -> None:
    for column, label in [("shaking_class", "Same ground shaking"), ("wind_class", "Same wind")]:
        events = game_data.similar_events(conn, column, asteroid[column], excluded_dis_no)
        if events:
            names = ", ".join(f"{disaster_title(event)} ({event['country']}, {event['year']})" for event in events)
            st.caption(f"{label} ({asteroid[column]}) as: {names}")


def show_result(conn, duel) -> None:
    deaths_pick, damage_pick = st.session_state.picks
    show_answer("Deaths", deaths_pick, duel.asteroid["deaths"], duel.disaster["deaths"], people)
    if duel.asks_damage:
        show_answer("Damage", damage_pick, duel.asteroid["damage_usd"], duel.disaster["damage_usd"], dollars)
    else:
        st.caption("EM-DAT has no damage figure for this disaster: only the deaths question counted.")
    show_similar_events(conn, duel.asteroid, duel.disaster["dis_no"])
    last_round = st.session_state.round_number == ROUNDS_PER_GAME
    if st.button("See my score" if last_round else "Next round", type="primary"):
        st.session_state.update(round_number=st.session_state.round_number + 1, duel=None, picks=None)
        st.rerun()


def show_round(conn, duel) -> None:
    round_number = st.session_state.round_number
    st.progress(round_number / ROUNDS_PER_GAME,
                text=f"Round {round_number} of {ROUNDS_PER_GAME} · score {st.session_state.points}"
                     f"/{st.session_state.questions}")
    show_asteroid(duel.asteroid)
    st.markdown("**versus**")
    show_disaster(duel.disaster)
    st.divider()
    if st.session_state.picks:
        show_result(conn, duel)
        return
    deaths_pick = ask("Which caused more deaths?", f"deaths-{round_number}")
    damage_pick = ask("Which caused more material damage?", f"damage-{round_number}") if duel.asks_damage else None
    is_answered = deaths_pick is not None and (damage_pick is not None or not duel.asks_damage)
    if st.button("Reveal", type="primary", disabled=not is_answered):
        points, questions = score(duel, deaths_pick, damage_pick)
        st.session_state.update(points=st.session_state.points + points,
                                questions=st.session_state.questions + questions,
                                picks=(deaths_pick, damage_pick))
        st.rerun()


def show_final_score() -> None:
    st.subheader(f"Final score: {st.session_state.points} / {st.session_state.questions}")
    if st.button("Play again", type="primary"):
        new_game()
        st.rerun()


st.title("Impact Duel")
st.caption("Asteroid vs. historical disaster: which is worse? Asteroid tolls are educational "
           "order-of-magnitude estimates, not predictions.")

if "round_number" not in st.session_state:
    new_game()

if st.session_state.round_number > ROUNDS_PER_GAME:
    show_final_score()
    st.stop()

try:
    with game_data.connect() as connection:
        if st.session_state.duel is None:
            st.session_state.duel = draw_duel(connection)
        if st.session_state.duel is None:
            st.error(f"Not enough game data to draw a fair duel. {PIPELINE_HINT}")
        else:
            show_round(connection, st.session_state.duel)
except psycopg.Error as error:
    st.error(f"Cannot read the warehouse: {error}. {PIPELINE_HINT}")
