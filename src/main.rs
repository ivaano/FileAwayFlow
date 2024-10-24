mod handler;
mod model;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4};


use serde::Serialize;
use warp::{http::Method, Filter, Rejection, reject};
use std::env;
use lazy_static::lazy_static;

type WebResult<T> = Result<T, Rejection>;

#[derive(Serialize)]
pub struct GenericResponse {
    pub status: String,
    pub message: String,
}



#[tokio::main]
async fn main() {
    let args: Vec<String> = env::args().collect();
    let default_port = "8000".to_string();
    let port = args.get(1).unwrap_or(&default_port);
    let port_int: i32 = match port.parse() {
        Ok(port) => port,
        Err(_) => {
            eprintln!("Invalid port number");
            std::process::exit(1);
        }
    };

    if env::var_os("RUST_LOG").is_none() {
        env::set_var("RUST_LOG", "api=info");
    }
    pretty_env_logger::init();
    lazy_static! {
        static ref EXPECTED_API_KEY: String = env::var("API_KEY").unwrap_or("123456".to_string());
    }
    fn key_validation() -> impl Filter<Extract = (), Error = Rejection> + Copy {

        warp::header("X-API-KEY")
            .and_then(|key: String| async move {
                if key == *EXPECTED_API_KEY {
                    Ok(())
                } else {
                    Err(reject::custom(ApiKeyError))
                }
            })
            .untuple_one()
    }

    let cors = warp::cors()
        .allow_any_origin()
        .allow_methods(&[Method::GET, Method::POST])
        .allow_header("content-type")
        .allow_header("X-API-KEY");

    let health_checker = warp::path("api")
        .and(warp::path("health"))
        .and(warp::get())
        .and_then(handler::health_checker_handler);


    let file_move_route = warp::path!("api" / "files" / "move");
    let files_routes = file_move_route
        .and(key_validation())
        .and(warp::post())
        .and(warp::body::json())
        .and_then(handler::handle_file_move)
        .or(health_checker);

    let files_routes = files_routes.recover(handler::handle_rejection);
    
    let routes = files_routes
        .with(cors)
        .with(warp::log("api"))
        .or(health_checker);

    println!("🚀 Server started successfully, listening on port {}", port_int);
    if "123456" == *EXPECTED_API_KEY {
        println!("WARNING!!!! Using default API Key: {}", *EXPECTED_API_KEY);
    }
    warp::serve(routes).run(SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::new(0, 0, 0, 0), port_int as u16))).await;
}

#[derive(Debug)]
struct ApiKeyError;

impl reject::Reject for ApiKeyError {}