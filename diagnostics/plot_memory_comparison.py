"""Plot saved external memory comparisons; run with the reporting environment."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('comparison',type=Path)
    parser.add_argument('--output',type=Path,required=True,help='Output stem for SVG and PNG')
    args=parser.parse_args();report=json.loads(args.comparison.read_text())
    groups=defaultdict(list)
    for match in report['matches']:
        sample=next((s for s in match['samples'] if s['requested_offset_s']==60),None)
        if sample:groups[match['pid']].append((match,sample))
    fig,axes=plt.subplots(1,2,figsize=(11,5))
    colors=['#176a9f','#cb641c','#387b44','#8752a1']
    fields=[('private_mib','Private memory (MiB)'),('largest_free_region_mib','Largest free address-space region (MiB)')]
    for index,(pid,matches) in enumerate(groups.items()):
        x=list(range(1,len(matches)+1));color=colors[index%len(colors)]
        saved=sum(m['completion_saved'] for m,_ in matches)
        label=f'Process {pid}: {saved} saved / {len(matches)} sampled'
        for ax,(field,title) in zip(axes,fields):
            y=[s[field] for _,s in matches]
            ax.plot(x,y,color=color,linewidth=2,label=label)
            for xi,yi,(match,_) in zip(x,y,matches):
                ax.scatter([xi],[yi],s=46,facecolor=color if match['completion_saved'] else 'white',edgecolor=color,zorder=3)
                neighbors=[series[xi-1][1][field] for series in groups.values() if len(series)>=xi]
                above=yi>=max(neighbors)
                if len(neighbors)>1 and min(neighbors)==max(neighbors):above=index%2==0
                ax.annotate(f'{yi:.0f}',(xi,yi),xytext=(0,9 if above else -17),textcoords='offset points',ha='center',fontsize=9,color=color)
    for ax,(_,title) in zip(axes,fields):
        ax.set_title(title,fontsize=11);ax.set_xlabel('Match number within the same process')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True));ax.grid(alpha=.22)
        ax.spines[['top','right']].set_visible(False);ax.margins(x=.16,y=.23)
    axes[1].set_ylim(bottom=0)
    fig.suptitle('Fixed-faction repeat loads: approximately one minute after loading',fontsize=14,y=.97)
    fig.text(.5,.895,'75 VP | 10,000 base MP | German heroic vs Soviet easy | Low textures',ha='center',fontsize=10,color='#444444')
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,.08),frameon=False,ncol=2,fontsize=9)
    stamp=datetime.fromtimestamp(report['generated_at']).strftime('%Y-%m-%d %H:%M local')
    fig.text(.5,.04,'Open marker: match still in progress. Approximate timing and different simulations; instrumentation overhead not subtracted.',ha='center',fontsize=8,color='#555555')
    fig.text(.5,.012,f'External memory observations | {stamp}',ha='center',fontsize=8,color='#555555')
    fig.subplots_adjust(top=.8,bottom=.25,wspace=.3)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for suffix in ['.svg','.png']:fig.savefig(args.output.with_suffix(suffix),dpi=150,facecolor='white')
    plt.close(fig)
    print(args.output.with_suffix('.svg'))


if __name__=='__main__':main()
