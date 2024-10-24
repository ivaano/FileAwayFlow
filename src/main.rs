mod handler;
mod model;


use serde::Serialize;
use warp::{http::Method, Filter, Rejection, reject};


type WebResult<T> = std::result::Result<T, Rejection>;

#[derive(Serialize)]
pub struct GenericResponse {
    pub status: String,
    pub message: String,
}



#[tokio::main]
async fn main() {
    if std::env::var_os("RUST_LOG").is_none() {
        std::env::set_var("RUST_LOG", "api=info");
    }
    pretty_env_logger::init();
    const EXPECTED_API_KEY: &str = "123456";

    fn key_validation() -> impl Filter<Extract = (), Error = Rejection> + Copy {
        warp::header("X-API-KEY")
            .and_then(|key: String| async move {
                if key == EXPECTED_API_KEY {
                    Ok(())
                } else {
                    Err(reject::custom(ApiKeyError))
                }
            })
            .untuple_one()
    }


    let file_move_route = warp::path!("api" / "files" / "move");
    let health_checker = warp::path!("api" / "health")
        .and(warp::get())
        .and_then(handler::health_checker_handler);
    
    let cors = warp::cors()
        .allow_any_origin()
        .allow_methods(&[Method::GET, Method::POST])
        .allow_header("content-type")
        .allow_header("authorization");

    let files_routes = file_move_route
        .and(key_validation())
        .and(warp::post())
        .and(warp::body::json())
        .and_then(handler::handle_file_move);

    let files_routes = files_routes.recover(handler::handle_rejection);
    
    let routes = files_routes
        .with(cors)
        .with(warp::log("api"))
        .or(health_checker);

    println!("🚀 Server started successfully");
    warp::serve(routes).run(([0, 0, 0, 0], 8000)).await;
}

#[derive(Debug)]
struct ApiKeyError;

impl warp::reject::Reject for ApiKeyError {}