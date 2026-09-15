import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;
import java.util.LinkedHashSet;

// Run only with -readOnly -noanalysis. New function definitions are not saved.
public class AnalyzeTactical extends GhidraScript {
    public void run() throws Exception {
        String[] args=getScriptArgs();
        LinkedHashSet<Function> functions=new LinkedHashSet<>();
        try(PrintWriter out=new PrintWriter(args[0])) {
            for(int i=1;i<args.length;i++) {
                boolean refs=args[i].startsWith("x");
                var address=toAddr(Long.parseLong(refs?args[i].substring(1):args[i],16));
                if(refs) {
                    for(Reference ref:getReferencesTo(address)) {
                        Function f=getFunctionContaining(ref.getFromAddress());
                        out.println("REF "+address+" "+ref.getFromAddress()+" "+f);
                        if(f!=null) functions.add(f);
                    }
                } else {
                    Function f=getFunctionAt(address);
                    if(f==null) {
                        f=getFunctionContaining(address);
                        if(f==null) { disassemble(address); f=createFunction(address,null); }
                    }
                    if(f!=null) functions.add(f); else out.println("UNRESOLVED "+address);
                }
            }
            DecompInterface d=new DecompInterface(); d.openProgram(currentProgram);
            for(Function f:functions) {
                out.println("\nFUNCTION "+f.getEntryPoint()+" "+f.getName());
                var result=d.decompileFunction(f,30,monitor);
                out.println(result.decompileCompleted()?result.getDecompiledFunction().getC():result.getErrorMessage());
                out.flush();
            }
            d.dispose();
        }
    }
}
