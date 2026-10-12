import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadLocalRandom;

/**
 * API mínima de "pedidos" (só JDK + driver JDBC do PostgreSQL), sem nenhuma
 * linha de OpenTelemetry no código: toda a telemetria vem do Java agent.
 *
 * Rotas:
 *   GET  /pedidos         -> SELECT dos 10 pedidos mais recentes
 *   POST /pedidos         -> INSERT de um pedido aleatório
 *   GET  /pedidos/lento   -> SELECT pg_sleep(0.05) (consulta "lenta")
 *   GET  /saude           -> 200 sem tocar no banco
 */
public class App {

    private static final String JDBC_URL = env("JDBC_URL", "jdbc:postgresql://postgres:5432/pedidos?currentSchema=public");
    private static final String DB_USER = env("DB_USER", "app");
    private static final String DB_PASSWORD = env("DB_PASSWORD", "app");

    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(env("PORT", "8080"));
        criarTabela();

        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext("/pedidos", App::pedidos);
        server.createContext("/saude", ex -> responder(ex, 200, "ok\n"));
        server.setExecutor(Executors.newFixedThreadPool(8));
        server.start();
        System.out.println("pedidos-api ouvindo na porta " + port);
    }

    private static void pedidos(HttpExchange ex) throws IOException {
        String path = ex.getRequestURI().getPath();
        String metodo = ex.getRequestMethod();
        try (Connection c = conectar()) {
            if (path.equals("/pedidos/lento") && metodo.equals("GET")) {
                try (Statement st = c.createStatement()) {
                    st.execute("SELECT pg_sleep(0.05)");
                }
                responder(ex, 200, "ok (lento)\n");
            } else if (path.equals("/pedidos") && metodo.equals("POST")) {
                try (PreparedStatement ps = c.prepareStatement(
                        "INSERT INTO pedidos (cliente, valor) VALUES (?, ?)")) {
                    ps.setString(1, "cliente-" + ThreadLocalRandom.current().nextInt(1, 500));
                    ps.setDouble(2, ThreadLocalRandom.current().nextDouble(10, 900));
                    ps.executeUpdate();
                }
                responder(ex, 201, "criado\n");
            } else if (path.equals("/pedidos") && metodo.equals("GET")) {
                StringBuilder sb = new StringBuilder();
                try (PreparedStatement ps = c.prepareStatement(
                        "SELECT id, cliente, valor FROM pedidos ORDER BY id DESC LIMIT 10");
                     ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        sb.append(rs.getLong(1)).append(';').append(rs.getString(2)).append(';')
                          .append(String.format("%.2f", rs.getDouble(3))).append('\n');
                    }
                }
                responder(ex, 200, sb.toString());
            } else {
                responder(ex, 404, "rota não encontrada\n");
            }
        } catch (SQLException e) {
            responder(ex, 500, "erro de banco: " + e.getMessage() + "\n");
        }
    }

    private static void criarTabela() throws InterruptedException {
        for (int tentativa = 1; tentativa <= 30; tentativa++) {
            try (Connection c = conectar(); Statement st = c.createStatement()) {
                st.execute("CREATE TABLE IF NOT EXISTS pedidos ("
                        + "id BIGSERIAL PRIMARY KEY, cliente TEXT NOT NULL, "
                        + "valor NUMERIC(10,2) NOT NULL, criado_em TIMESTAMPTZ DEFAULT now())");
                return;
            } catch (SQLException e) {
                System.out.println("aguardando o PostgreSQL (" + tentativa + "/30): " + e.getMessage());
                Thread.sleep(2000);
            }
        }
        throw new IllegalStateException("PostgreSQL indisponível");
    }

    private static Connection conectar() throws SQLException {
        return DriverManager.getConnection(JDBC_URL, DB_USER, DB_PASSWORD);
    }

    private static void responder(HttpExchange ex, int status, String corpo) throws IOException {
        byte[] bytes = corpo.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "text/plain; charset=utf-8");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static String env(String nome, String padrao) {
        String v = System.getenv(nome);
        return (v == null || v.isBlank()) ? padrao : v;
    }
}
