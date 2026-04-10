const circleContainer = document.getElementById("circleContainer");

const numBars = 50;
let activeBars = 0;

for(let i = 0; i < numBars; i++){
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.transform = `rotate(${(360 / numBars) * i}deg) translateY(-170px)`;
    circleContainer.appendChild(bar)
}

function animateBars(){
    const bars = document.querySelectorAll(".bar");

    setInterval(()=>{
        bars[activeBars % numBars].classList.add("active");

        if(activeBars > 8){
            bars[(activeBars - 8) % numBars].classList.remove("active");
        }

        activeBars++;

    }, 100);
}

animateBars();