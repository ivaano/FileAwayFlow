use warp::{Filter, Rejection, Reply};
use crate::handler;
use crate::EXPECTED_API_KEY;
use crate::ApiKeyError;

pub fn health_checker() -> impl Filter<Extract = impl Reply, Error = Rejection> + Clone {
    warp::path("api")
        .and(warp::path("health"))
        .and(warp::get())
        .and_then(handler::health_checker_handler)
}

pub fn key_validation() -> impl Filter<Extract = (), Error = Rejection> + Copy {
    warp::header("X-API-KEY")
        .and_then(|key: String| async move {
            if key == *EXPECTED_API_KEY {
                Ok(())
            } else {
                Err(warp::reject::custom(ApiKeyError))
            }
        })
        .untuple_one()
}

pub fn files_routes() -> impl Filter<Extract = impl Reply, Error = Rejection> + Clone + warp::Filter {
    let file_move_route = warp::path!("api" / "files" / "move");
    let routes = file_move_route
        .and(key_validation())
        .and(warp::post())
        .and(warp::body::json())
        .and_then(handler::handle_file_move)
        .or(health_checker());

    routes.recover(handler::handle_rejection)
}