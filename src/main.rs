use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4};
use warp::http::Method;
use std::env;
use warp::Filter;

#[tokio::main]
async fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() > 1 && args[1] == "--version" {
        println!("Version {}", env!("CARGO_PKG_VERSION"));
        std::process::exit(0);
    }

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

    let cors = warp::cors()
        .allow_any_origin()
        .allow_methods(&[Method::GET, Method::POST])
        .allow_header("content-type")
        .allow_header("X-API-KEY");

    let routes = file_away_flow::files_routes()
        .with(cors)
        .with(warp::log("api"));

    println!("🚀 FileAwayFlow v{} server started successfully, listening on port {}",
             env!("CARGO_PKG_VERSION"),
             port_int
    );

    if "123456" == *file_away_flow::EXPECTED_API_KEY {
        println!("WARNING!!!! Using default API Key: {}", *file_away_flow::EXPECTED_API_KEY);
    }

    // Start the server
    warp::serve(routes)
        .run(SocketAddr::V4(SocketAddrV4::new(
            Ipv4Addr::new(0, 0, 0, 0),
            port_int as u16
        )))
        .await;
}